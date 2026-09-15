from __future__ import annotations

import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.database import SessionLocal
from app.models import Report, ReportStatus
from app.services.report_service import ReportProcessor
from sqlalchemy import select
from app.routers import api, pages


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    init_db()
    async def recover_pending() -> None:
        await asyncio.sleep(0.5)
        with SessionLocal() as session:
            statement = select(Report.id).where(Report.status.in_((ReportStatus.UPLOADED.value, ReportStatus.PROCESSING.value)))
            pending = list(session.scalars(statement))
        processor = ReportProcessor(settings, session_factory=SessionLocal)
        for report_id in pending:
            await processor.process(report_id)

    recovery_task = asyncio.create_task(recover_pending())
    try:
        yield
    finally:
        recovery_task.cancel()


app = FastAPI(
    title="주간업무일지 LLM 요약 시스템",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(api.router)
app.mount("/legacy/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages.router)

# Vite's production bundle is served by FastAPI so the VM needs only one port.
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
app.mount("/", StaticFiles(directory=frontend_dist, html=True, check_dir=False), name="frontend")
