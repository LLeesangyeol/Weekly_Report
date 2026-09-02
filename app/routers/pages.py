from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.report_repository import ReportRepository


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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


templates.env.filters["display_item"] = display_item


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    reports = ReportRepository(db).list(limit=100)
    return templates.TemplateResponse(request=request, name="index.html", context={"reports": reports})


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
    return templates.TemplateResponse(request=request, name="team_summary.html", context={"batch_id": batch_id, "reports": reports})
