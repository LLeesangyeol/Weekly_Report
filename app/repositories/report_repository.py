from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import String, delete, or_, desc, select
from sqlalchemy.orm import Session

from app.models import DocumentChunk, Report, ReportStatus, utcnow


class ReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        file_path: str,
        file_size: int,
        content_type: str,
        source_type: str,
        model_name: str,
        batch_id: str | None = None,
        report_date: date | None = None,
        department: str | None = None,
        author: str | None = None,
        checksum_sha256: str | None = None,
    ) -> Report:
        report = Report(
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            file_size=file_size,
            content_type=content_type,
            source_type=source_type,
            model_name=model_name,
            batch_id=batch_id,
            report_date=report_date,
            department=department,
            author=author,
            checksum_sha256=checksum_sha256,
            status=ReportStatus.UPLOADED.value,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def get(self, report_id: int) -> Report | None:
        return self.session.get(Report, report_id)

    def get_by_checksum(self, checksum_sha256: str, original_filename: str | None = None) -> Report | None:
        statement = select(Report).where(Report.checksum_sha256 == checksum_sha256)
        if original_filename:
            statement = statement.where(Report.original_filename == original_filename)
        statement = statement.order_by(desc(Report.created_at))
        return self.session.scalar(statement)

    def list(self, *, limit: int = 100, offset: int = 0, include_deleted: bool = False) -> list[Report]:
        statement = select(Report)
        if not include_deleted:
            statement = statement.where(Report.deleted_at.is_(None))
        statement = statement.order_by(desc(Report.created_at)).limit(limit).offset(offset)
        return list(self.session.scalars(statement))

    def search(
        self,
        *,
        keyword: str | None = None,
        author: str | None = None,
        department: str | None = None,
        report_date: date | None = None,
        limit: int = 100,
    ) -> list[Report]:
        statement = select(Report).where(Report.deleted_at.is_(None))
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(or_(
                Report.author.ilike(pattern),
                Report.department.ilike(pattern),
                Report.original_filename.ilike(pattern),
                Report.planned_work.cast(String).ilike(pattern),
                Report.completed_work.cast(String).ilike(pattern),
                Report.extracted_text.ilike(pattern),
                Report.summary.ilike(pattern),
            ))
        if author:
            statement = statement.where(Report.author.ilike(f"%{author}%"))
        if department:
            statement = statement.where(Report.department.ilike(f"%{department}%"))
        if report_date:
            statement = statement.where(Report.report_date == report_date)
        return list(self.session.scalars(statement.order_by(desc(Report.created_at)).limit(limit)))

    def list_batch(self, batch_id: str) -> list[Report]:
        statement = select(Report).where(Report.batch_id == batch_id).order_by(Report.author, Report.id)
        return list(self.session.scalars(statement))

    def set_status(self, report: Report, status: ReportStatus, error: str | None = None) -> None:
        report.status = status.value
        report.error_message = error
        self.session.commit()

    def complete(self, report: Report, values: dict[str, Any]) -> None:
        for key, value in values.items():
            setattr(report, key, value)
        report.status = ReportStatus.COMPLETED.value
        report.error_message = None
        self.session.commit()

    def replace_chunks(self, report: Report, chunks: list[dict[str, Any]]) -> list[DocumentChunk]:
        self.session.execute(delete(DocumentChunk).where(DocumentChunk.report_id == report.id))
        values = [DocumentChunk(report_id=report.id, **chunk) for chunk in chunks]
        self.session.add_all(values)
        self.session.flush()
        report.chunk_count = len(values)
        report.index_status = "indexing"
        self.session.commit()
        return values

    def list_chunks(self, report_id: int) -> list[DocumentChunk]:
        statement = select(DocumentChunk).where(DocumentChunk.report_id == report_id).order_by(DocumentChunk.ordinal)
        return list(self.session.scalars(statement))

    def mark_indexed(self, report: Report) -> None:
        from app.models import utcnow
        report.index_status = "indexed"
        report.indexed_at = utcnow()
        self.session.commit()

    def mark_index_failed(self, report: Report, error: str) -> None:
        report.index_status = "failed"
        report.error_message = error[:2000]
        self.session.commit()

    def move_to_trash(self, report: Report) -> None:
        report.deleted_at = utcnow()
        self.session.commit()

    def restore(self, report: Report) -> None:
        report.deleted_at = None
        self.session.commit()
