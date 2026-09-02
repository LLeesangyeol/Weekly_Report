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
                    structured = await self.ollama_service.structure_document(
                        extracted,
                        report_date=report.report_date.isoformat() if report.report_date else None,
                        department=report.department,
                        author=report.author,
                    )
                summary = await self.ollama_service.summarize(structured)
                values = structured.model_dump()
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
                })
            except Exception as exc:
                session.rollback()
                report = repository.get(report_id)
                if report is not None:
                    # Store a bounded, user-actionable error; never include document content.
                    repository.set_status(report, ReportStatus.FAILED, str(exc)[:2000])
                logger.exception("Report processing failed for id=%s (%s)", report_id, type(exc).__name__)
