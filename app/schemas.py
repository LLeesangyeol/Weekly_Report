from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


KST = timezone(timedelta(hours=9), name="Asia/Seoul")


def to_kst(value: datetime) -> datetime:
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return utc_value.astimezone(KST)


class StructuredReport(BaseModel):
    report_date: str | None = None
    department: str | None = None
    author: str | None = None
    planned_work: list[Any] = Field(default_factory=list)
    completed_work: list[Any] = Field(default_factory=list)
    weekly_schedule: list[Any] = Field(default_factory=list)
    issues: list[Any] = Field(default_factory=list)
    next_week_plan: list[Any] = Field(default_factory=list)

    @field_validator(
        "planned_work", "completed_work", "weekly_schedule", "issues", "next_week_plan",
        mode="before",
    )
    @classmethod
    def empty_arrays(cls, value: Any) -> list[Any]:
        return [] if value is None else value


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date | None
    department: str | None
    author: str | None
    planned_work: list[Any]
    completed_work: list[Any]
    weekly_schedule: list[Any]
    issues: list[Any]
    next_week_plan: list[Any]
    extracted_text: str | None
    structured_json: dict[str, Any] | None
    summary: str | None
    original_filename: str
    stored_filename: str
    file_size: int
    content_type: str
    source_type: str
    model_name: str
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_kst_datetime(self, value: datetime) -> str:
        return to_kst(value).isoformat()


class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date | None
    department: str | None
    author: str | None
    original_filename: str
    status: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_kst_datetime(self, value: datetime) -> str:
        return to_kst(value).isoformat()


class ReportStatusRead(BaseModel):
    id: int
    status: str
    error_message: str | None = None


class ReportCreated(BaseModel):
    id: int
    status: str
    status_url: str


class BatchReportCreated(BaseModel):
    id: int
    status: str
    status_url: str


class BatchCreated(BaseModel):
    batch_id: str
    reports: list[BatchReportCreated]
    team_summary_url: str
