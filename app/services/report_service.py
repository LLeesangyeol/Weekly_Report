from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal
from app.models import ReportStatus
from app.repositories.report_repository import ReportRepository
from app.services.document_service import DocumentService
from app.services.ollama_service import OllamaService
from app.services.weekly_template_service import parse_weekly_report_template
from app.services.document_preview_service import DocumentPreviewService, PreviewError
from app.services.document_summary_service import summarize_structured_document
from app.services.chunking_service import chunk_document
from app.services.vector_store_service import get_vector_store


logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        matched = re.fullmatch(r"\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*", value)
        if not matched:
            return None
        try:
            return date(*(int(part) for part in matched.groups()))
        except ValueError:
            return None


class ReportProcessor:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        document_service: DocumentService | None = None,
        ollama_service: OllamaService | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.document_service = document_service or DocumentService(settings)
        self.ollama_service = ollama_service or OllamaService(settings)
        self.preview_service = DocumentPreviewService(settings)

    async def process(self, report_id: int) -> None:
        with self.session_factory() as session:
            repository = ReportRepository(session)
            report = repository.get(report_id)
            if report is None:
                logger.warning("Background job received unknown report id=%s", report_id)
                return
            repository.set_status(report, ReportStatus.PROCESSING)
            try:
                # Deliberately never log extracted document text or LLM prompts.
                extracted = self.document_service.extract(Path(report.file_path))
                structured = parse_weekly_report_template(extracted)
                if structured is None:
                    if structural_summary := summarize_structured_document(extracted):
                        summary = structural_summary
                    elif len(extracted) > 180_000:
                        summary = (
                            "대용량 참고 문서입니다. 문서 전체를 검색 인덱스에 등록했으며, "
                            "AI 통합검색에서 취약점 항목·점검 기준·조치 방법으로 찾아볼 수 있습니다."
                        )
                    else:
                        summary = await self.ollama_service.summarize_document(extracted)
                    from app.schemas import StructuredReport
                    structured = StructuredReport(
                        report_date=report.report_date.isoformat() if report.report_date else None,
                        department=report.department,
                        author=report.author,
                    )
                else:
                    summary = await self.ollama_service.summarize(structured)
                values = structured.model_dump()
                try:
                    preview_path = str(self.preview_service.create(Path(report.file_path), report.id))
                except PreviewError:
                    preview_path = None
                repository.complete(report, {
                    "report_date": report.report_date or _parse_date(structured.report_date),
                    "department": report.department or structured.department,
                    "author": report.author or structured.author,
                    "planned_work": values["planned_work"],
                    "completed_work": values["completed_work"],
                    "weekly_schedule": values["weekly_schedule"],
                    "issues": values["issues"],
                    "next_week_plan": values["next_week_plan"],
                    "extracted_text": extracted,
                    "structured_json": values,
                    "summary": summary,
                    "preview_path": preview_path,
                })
                chunks = chunk_document(
                    extracted,
                    size=self.settings.rag_chunk_size,
                    overlap=self.settings.rag_chunk_overlap,
                )
                stored_chunks = repository.replace_chunks(report, [
                    {
                        "ordinal": chunk.ordinal,
                        "page_number": chunk.page_number,
                        "heading": chunk.heading,
                        "content": chunk.content,
                        "token_estimate": max(1, len(chunk.content) // 3),
                    }
                    for chunk in chunks
                ])
                vectors: list[list[float]] = []
                batch_size = self.settings.embedding_batch_size
                for start in range(0, len(stored_chunks), batch_size):
                    batch = stored_chunks[start:start + batch_size]
                    vectors.extend(await self.ollama_service.embed([item.content for item in batch]))
                get_vector_store(self.settings).index(report, stored_chunks, vectors)
                repository.mark_indexed(report)
            except Exception as exc:
                session.rollback()
                report = repository.get(report_id)
                if report is not None:
                    # Store a bounded, user-actionable error; never include document content.
                    repository.set_status(report, ReportStatus.FAILED, str(exc)[:2000])
                logger.exception("Report processing failed for id=%s (%s)", report_id, type(exc).__name__)

    async def reindex(self, report_id: int) -> None:
        with self.session_factory() as session:
            repository = ReportRepository(session)
            report = repository.get(report_id)
            if report is None or not report.extracted_text:
                return
            report.index_status = "indexing"
            session.commit()
            try:
                chunks = chunk_document(report.extracted_text, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap)
                stored_chunks = repository.replace_chunks(report, [
                    {"ordinal": item.ordinal, "page_number": item.page_number, "heading": item.heading,
                     "content": item.content, "token_estimate": max(1, len(item.content) // 3)}
                    for item in chunks
                ])
                vectors: list[list[float]] = []
                for start in range(0, len(stored_chunks), self.settings.embedding_batch_size):
                    batch = stored_chunks[start:start + self.settings.embedding_batch_size]
                    vectors.extend(await self.ollama_service.embed([item.content for item in batch]))
                get_vector_store(self.settings).index(report, stored_chunks, vectors)
                repository.mark_indexed(report)
            except Exception as exc:
                session.rollback()
                report = repository.get(report_id)
                if report:
                    repository.mark_index_failed(report, str(exc))
                logger.exception("Report reindex failed for id=%s", report_id)
