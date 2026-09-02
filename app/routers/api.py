from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal, get_db
from app.repositories.report_repository import ReportRepository
from app.schemas import BatchCreated, BatchReportCreated, ReportCreated, ReportListItem, ReportRead, ReportStatusRead
from app.services.report_service import ReportProcessor
from app.services.storage_service import InsufficientStorageError, StorageService, UploadValidationError


router = APIRouter(prefix="/api")


def get_report_processor(settings: Settings = Depends(get_settings)) -> ReportProcessor:
    return ReportProcessor(settings, session_factory=SessionLocal)


def _clean_optional(value: str | None, field: str, max_length: int = 200) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise HTTPException(status_code=422, detail=f"{field}은(는) {max_length}자 이하여야 합니다.")
    return cleaned


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
    report_date: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list:
    repository = ReportRepository(db)
    if any((keyword, author, department, report_date)):
        return repository.search(keyword=keyword, author=author, department=department, report_date=report_date, limit=limit)
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


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="데이터베이스 연결에 실패했습니다.") from exc
    return {"status": "ok", "database": "ok"}
