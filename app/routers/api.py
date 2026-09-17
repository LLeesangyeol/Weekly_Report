from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal, get_db
from app.models import DocumentChunk, Report
from app.repositories.report_repository import ReportRepository
from app.schemas import (
    BatchCreated, BatchReportCreated, GeneralChatRequest, KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeSource, ReportCreated, ReportListItem, ReportRead, ReportStatusRead,
)
from app.services.knowledge_search_service import KnowledgeSearchService
from app.services.ollama_service import OllamaService
from app.services.vector_store_service import get_vector_store
import httpx
from app.services.report_service import ReportProcessor
from app.services.storage_service import InsufficientStorageError, StorageService, UploadValidationError


router = APIRouter(prefix="/api")


def get_report_processor(settings: Settings = Depends(get_settings)) -> ReportProcessor:
    return ReportProcessor(settings, session_factory=SessionLocal)


@router.delete("/reports")
def delete_all_reports(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    """Remove every uploaded document and its search data; app source is never in scope."""
    reports = list(db.scalars(select(Report)))
    report_count = len(reports)
    chunk_count = db.scalar(select(func.count()).select_from(DocumentChunk)) or 0

    vector_store = get_vector_store(settings)
    if vector_store.client.collection_exists(vector_store.collection):
        vector_store.client.delete_collection(vector_store.collection)

    upload_root = settings.upload_dir.resolve()
    deleted_files = 0
    for report in reports:
        try:
            file_path = Path(report.file_path).resolve()
            if file_path.is_relative_to(upload_root) and file_path.is_file():
                file_path.unlink()
                deleted_files += 1
        except OSError:
            # The database deletion still proceeds: missing or locked old originals must not retain search data.
            continue

    db.execute(delete(DocumentChunk))
    db.execute(delete(Report))
    db.commit()
    return {"reports_deleted": report_count, "chunks_deleted": chunk_count, "original_files_deleted": deleted_files}


@router.post("/ai/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeSearchResponse:
    answer, hits, mode = await KnowledgeSearchService(
        db,
        OllamaService(settings),
        get_vector_store(settings),
        min_semantic_score=settings.rag_min_semantic_score,
    ).answer(
        request.query, request.limit
    )
    return KnowledgeSearchResponse(
        answer=answer,
        mode=mode,
        sources=[
            KnowledgeSource(
                id=hit.report.id,
                filename=hit.report.original_filename,
                snippet=hit.snippet,
                score=hit.score,
                report_date=hit.report.report_date,
                author=hit.report.author,
                page_number=hit.page_number,
                heading=hit.heading,
            )
            for hit in hits
        ],
    )


@router.post("/ai/chat", response_model=KnowledgeSearchResponse)
async def general_chat(
    request: GeneralChatRequest,
    settings: Settings = Depends(get_settings),
) -> KnowledgeSearchResponse:
    answer = await OllamaService(settings).general_chat(
        request.message,
        [turn.model_dump() for turn in request.history],
    )
    return KnowledgeSearchResponse(answer=answer, mode="chat", sources=[])


@router.post("/reports/{report_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
def reindex_report(
    report_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    processor: ReportProcessor = Depends(get_report_processor),
) -> dict[str, object]:
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if not report.extracted_text:
        raise HTTPException(status_code=409, detail="추출된 원문이 없어 재색인할 수 없습니다.")
    report.index_status = "queued"
    db.commit()
    background_tasks.add_task(processor.reindex, report_id)
    return {"id": report_id, "index_status": "queued"}


@router.post("/reports/{report_id}/trash")
def trash_report(report_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, object]:
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    ReportRepository(db).move_to_trash(report)
    get_vector_store(settings).delete_report(report_id)
    return {"id": report_id, "deleted_at": report.deleted_at}


@router.post("/reports/{report_id}/restore")
def restore_report(report_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), processor: ReportProcessor = Depends(get_report_processor)) -> dict[str, object]:
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    ReportRepository(db).restore(report)
    if report.extracted_text:
        report.index_status = "queued"
        db.commit()
        background_tasks.add_task(processor.reindex, report_id)
    return {"id": report_id, "restored": True}


@router.post("/index/rebuild", status_code=status.HTTP_202_ACCEPTED)
def rebuild_index(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    processor: ReportProcessor = Depends(get_report_processor),
) -> dict[str, object]:
    reports = [item for item in ReportRepository(db).list(limit=500) if item.extracted_text]
    for report in reports:
        report.index_status = "queued"
        background_tasks.add_task(processor.reindex, report.id)
    db.commit()
    return {"queued": len(reports)}


@router.get("/system/status")
async def system_status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    counts = {"documents": 0, "indexed": 0, "failed": 0, "chunks": 0}
    reports = ReportRepository(db).list(limit=500)
    counts["documents"] = len(reports)
    counts["indexed"] = sum(item.index_status == "indexed" for item in reports)
    counts["failed"] = sum(item.status == "failed" or item.index_status == "failed" for item in reports)
    counts["chunks"] = sum(item.chunk_count or 0 for item in reports)
    try:
        vector = get_vector_store(settings).status()
    except Exception as exc:
        vector = {"status": "error", "detail": str(exc)[:200]}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            response.raise_for_status()
            models = [item.get("name") for item in response.json().get("models", [])]
        available = {name.split(":", 1)[0] for name in models if name}
        ollama = {"status": "ok", "chat_model": settings.ollama_model,
                  "embedding_model": settings.embedding_model,
                  "models_ready": settings.ollama_model in models and settings.embedding_model.split(":", 1)[0] in available}
    except Exception as exc:
        ollama = {"status": "error", "detail": str(exc)[:200]}
    return {"database": {"status": "ok", "driver": db.bind.dialect.name}, "vector": vector, "ollama": ollama, "counts": counts}


def _clean_optional(value: str | None, field: str, max_length: int = 200) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise HTTPException(status_code=422, detail=f"{field}은(는) {max_length}자 이하여야 합니다.")
    return cleaned


def _optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="기준일은 YYYY-MM-DD 형식이어야 합니다.") from exc


@router.post("/reports", response_model=ReportCreated, status_code=status.HTTP_202_ACCEPTED)
async def upload_report(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    author: Annotated[str | None, Form()] = None,
    department: Annotated[str | None, Form()] = None,
    report_date: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    processor: ReportProcessor = Depends(get_report_processor),
) -> ReportCreated:
    parsed_date: date | None = None
    if report_date and report_date.strip():
        try:
            parsed_date = date.fromisoformat(report_date.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="기준일은 YYYY-MM-DD 형식이어야 합니다.") from exc
    clean_author = _clean_optional(author, "작성자")
    clean_department = _clean_optional(department, "부서")
    storage = StorageService(settings)
    try:
        stored = await storage.save(file)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InsufficientStorageError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    existing = ReportRepository(db).get_by_checksum(stored.checksum_sha256, stored.original_filename)
    if existing is not None:
        stored.path.unlink(missing_ok=True)
        if existing.deleted_at:
            ReportRepository(db).restore(existing)
            background_tasks.add_task(processor.process, existing.id)
        return ReportCreated(id=existing.id, status=existing.status, status_url=f"/api/reports/{existing.id}/status")
    try:
        report = ReportRepository(db).create(
            original_filename=stored.original_filename,
            stored_filename=stored.stored_filename,
            file_path=str(stored.path),
            file_size=stored.size,
            content_type=stored.content_type,
            source_type=stored.source_type,
            model_name=settings.ollama_model,
            report_date=parsed_date,
            department=clean_department,
            author=clean_author,
            checksum_sha256=stored.checksum_sha256,
        )
    except Exception:
        stored.path.unlink(missing_ok=True)
        raise
    background_tasks.add_task(processor.process, report.id)
    return ReportCreated(id=report.id, status=report.status, status_url=f"/api/reports/{report.id}/status")


@router.post("/reports/batch", response_model=BatchCreated, status_code=status.HTTP_202_ACCEPTED)
async def upload_report_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    author: Annotated[str | None, Form()] = None,
    department: Annotated[str | None, Form()] = None,
    report_date: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    processor: ReportProcessor = Depends(get_report_processor),
) -> BatchCreated:
    if not 1 <= len(files) <= 10:
        raise HTTPException(status_code=400, detail="한 번에 1~10개의 보고서만 업로드할 수 있습니다.")
    parsed_date = None
    if report_date and report_date.strip():
        try:
            parsed_date = date.fromisoformat(report_date.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="기준일은 YYYY-MM-DD 형식이어야 합니다.") from exc
    clean_author = _clean_optional(author, "작성자")
    clean_department = _clean_optional(department, "부서")
    batch_id = str(uuid4())
    storage = StorageService(settings)
    created = []
    saved_paths: list[Path] = []
    try:
        for upload in files:
            stored = await storage.save(upload)
            saved_paths.append(stored.path)
            existing = ReportRepository(db).get_by_checksum(stored.checksum_sha256, stored.original_filename)
            if existing is not None:
                stored.path.unlink(missing_ok=True)
                saved_paths.remove(stored.path)
                if existing.deleted_at:
                    ReportRepository(db).restore(existing)
                    background_tasks.add_task(processor.process, existing.id)
                created.append(existing)
                continue
            report = ReportRepository(db).create(
                original_filename=stored.original_filename,
                stored_filename=stored.stored_filename,
                file_path=str(stored.path),
                file_size=stored.size,
                content_type=stored.content_type,
                source_type=stored.source_type,
                model_name=settings.ollama_model,
                batch_id=batch_id,
                report_date=parsed_date,
                department=clean_department,
                author=clean_author,
                checksum_sha256=stored.checksum_sha256,
            )
            created.append(report)
            background_tasks.add_task(processor.process, report.id)
    except (UploadValidationError, InsufficientStorageError) as exc:
        for path in saved_paths:
            path.unlink(missing_ok=True)
        status_code = 507 if isinstance(exc, InsufficientStorageError) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return BatchCreated(
        batch_id=batch_id,
        reports=[BatchReportCreated(id=report.id, status=report.status, status_url=f"/api/reports/{report.id}/status") for report in created],
        team_summary_url=f"/team-summary/{batch_id}",
    )


@router.get("/reports", response_model=list[ReportListItem])
def list_reports(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    keyword: str | None = Query(None, max_length=200),
    author: str | None = Query(None, max_length=200),
    department: str | None = Query(None, max_length=200),
    report_date: str | None = Query(None),
    trash: bool = Query(False),
    db: Session = Depends(get_db),
) -> list:
    parsed_date = _optional_date(report_date)
    repository = ReportRepository(db)
    if trash:
        return [report for report in repository.list(limit=limit, offset=offset, include_deleted=True) if report.deleted_at]
    if any((keyword, author, department, parsed_date)):
        return repository.search(keyword=keyword, author=author, department=department, report_date=parsed_date, limit=limit)
    return repository.list(limit=limit, offset=offset)


@router.get("/reports/{report_id}", response_model=ReportRead)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return report


@router.get("/reports/{report_id}/status", response_model=ReportStatusRead)
def get_report_status(report_id: int, db: Session = Depends(get_db)) -> ReportStatusRead:
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return ReportStatusRead(id=report.id, status=report.status, error_message=report.error_message)


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    try:
        path = StorageService(settings).safe_download_path(report.file_path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다.") from exc
    return FileResponse(path, media_type=report.content_type, filename=report.original_filename)


@router.get("/reports/{report_id}/preview")
def preview_report(report_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    report = ReportRepository(db).get(report_id)
    if report is None or not report.preview_path:
        raise HTTPException(status_code=404, detail="문서 미리보기가 아직 준비되지 않았습니다.")
    try:
        path = StorageService(settings).safe_download_path(report.preview_path)
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="문서 미리보기를 찾을 수 없습니다.") from exc
    return FileResponse(path, media_type="application/pdf", filename=f"{report.original_filename}.pdf")


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="데이터베이스 연결에 실패했습니다.") from exc
    return {"status": "ok", "database": "ok"}
