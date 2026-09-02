from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_work: Mapped[list[Any]] = mapped_column(JSON, default=list)
    completed_work: Mapped[list[Any]] = mapped_column(JSON, default=list)
    weekly_schedule: Mapped[list[Any]] = mapped_column(JSON, default=list)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    next_week_plan: Mapped[list[Any]] = mapped_column(JSON, default=list)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    file_path: Mapped[str] = mapped_column(String(1000))
    file_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20))
    model_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.UPLOADED.value, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
