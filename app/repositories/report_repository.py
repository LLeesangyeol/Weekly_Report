from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Report, ReportStatus


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
            status=ReportStatus.UPLOADED.value,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def get(self, report_id: int) -> Report | None:
        return self.session.get(Report, report_id)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[Report]:
        statement = select(Report).order_by(desc(Report.created_at)).limit(limit).offset(offset)
        return list(self.session.scalars(statement))

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
