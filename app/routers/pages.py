from __future__ import annotations

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.report_repository import ReportRepository


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
KST = timezone(timedelta(hours=9), name="Asia/Seoul")


def display_item(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        day = value.get("day")
        work = value.get("work") or value.get("schedule")
        if day and work:
            return f"{day}: {work}"
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def kst_datetime(value) -> str:
    if value is None:
        return "-"
    # SQLite returns naive datetimes; this app stores those values in UTC.
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return utc_value.astimezone(KST).strftime("%Y-%m-%d %H:%M")


templates.env.filters["display_item"] = display_item
templates.env.filters["kst_datetime"] = kst_datetime


def optional_date(value: str | None):
    if value is None or not value.strip():
        return None
    try:
        from datetime import date
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="기준일은 YYYY-MM-DD 형식이어야 합니다.") from exc


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    keyword: str | None = Query(None, max_length=200),
    author: str | None = Query(None, max_length=200),
    department: str | None = Query(None, max_length=200),
    report_date: str | None = Query(None),
    db: Session = Depends(get_db),
):
    parsed_date = optional_date(report_date)
    repository = ReportRepository(db)
    reports = repository.search(keyword=keyword, author=author, department=department, report_date=parsed_date) if any((keyword, author, department, parsed_date)) else repository.list(limit=100)
    return templates.TemplateResponse(request=request, name="index.html", context={"reports": reports, "filters": {"keyword": keyword or "", "author": author or "", "department": department or "", "report_date": parsed_date.isoformat() if parsed_date else ""}})


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(report_id: int, request: Request, db: Session = Depends(get_db)):
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return templates.TemplateResponse(request=request, name="detail.html", context={"report": report})


@router.get("/team-summary/{batch_id}", response_class=HTMLResponse)
def team_summary(batch_id: str, request: Request, db: Session = Depends(get_db)):
    reports = ReportRepository(db).list_batch(batch_id)
    if not reports:
        raise HTTPException(status_code=404, detail="업로드 묶음을 찾을 수 없습니다.")
    weekdays = ("월", "화", "수", "목", "금", "토", "일")
    weekday_names = {"월": "월요일", "화": "화요일", "수": "수요일", "목": "목요일", "금": "금요일", "토": "토요일", "일": "일요일"}
    schedules: dict[str, list[dict[str, str]]] = {day: [] for day in weekdays}
    for report in reports:
        for item in report.weekly_schedule or []:
            if not isinstance(item, dict) or not item.get("day") or not item.get("work"):
                continue
            key = str(item["day"])[:1]
            if key in schedules:
                schedules[key].append({"author": report.author or report.original_filename, "work": str(item["work"]), "date": str(item["day"])})
    grouped_schedule = [{"day": weekday_names[day], "items": schedules[day]} for day in weekdays]
    return templates.TemplateResponse(request=request, name="team_summary.html", context={"batch_id": batch_id, "reports": reports, "grouped_schedule": grouped_schedule})
