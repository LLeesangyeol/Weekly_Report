from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

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
    index_status: str = "pending"
    chunk_count: int = 0
    indexed_at: datetime | None = None
    deleted_at: datetime | None = None
    preview_path: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", "indexed_at", "deleted_at")
    def serialize_kst_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return to_kst(value).isoformat()


class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date | None
    department: str | None
    author: str | None
    original_filename: str
    file_size: int = 0
    content_type: str = "application/octet-stream"
    source_type: str = "file"
    status: str
    summary: str | None = None
    index_status: str = "pending"
    chunk_count: int = 0
    deleted_at: datetime | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_kst_datetime(self, value: datetime) -> str:
        return to_kst(value).isoformat()


class ReportStatusRead(BaseModel):
    id: int
    status: str
    error_message: str | None = None


class CalendarEventRead(BaseModel):
    report_id: int
    date: date
    author: str
    department: str | None = None
    schedule: str
    original_filename: str


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


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=30, ge=1, le=100)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class GeneralChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class KnowledgeSource(BaseModel):
    id: int
    filename: str
    snippet: str
    score: float
    report_date: date | None = None
    author: str | None = None
    page_number: int | None = None
    heading: str | None = None


class KnowledgeSearchResponse(BaseModel):
    answer: str
    sources: list[KnowledgeSource]
    mode: str
