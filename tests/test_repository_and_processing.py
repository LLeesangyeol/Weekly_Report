from __future__ import annotations

from pathlib import Path

import pytest

from app.models import ReportStatus
from app.repositories.report_repository import ReportRepository
from app.services.report_service import ReportProcessor


def create_report(db, path: Path):
    return ReportRepository(db).create(
        original_filename="report.pdf",
        stored_filename="00000000-0000-0000-0000-000000000000.pdf",
        file_path=str(path),
        file_size=10,
        content_type="application/pdf",
        source_type="pdf",
        model_name="test-model",
        author="사용자",
    )


def test_db_record_creation_and_status_change(db, tmp_path):
    report = create_report(db, tmp_path / "report.pdf")
    assert report.id is not None
    assert report.status == "uploaded"
    repository = ReportRepository(db)
    repository.set_status(report, ReportStatus.PROCESSING)
    assert repository.get(report.id).status == "processing"


class BrokenDocumentService:
    def extract(self, _path):
        raise RuntimeError("synthetic extraction failure")


@pytest.mark.asyncio
async def test_processing_error_sets_failed(settings, session_factory, tmp_path):
    with session_factory() as session:
        report_id = create_report(session, tmp_path / "report.pdf").id
    processor = ReportProcessor(
        settings,
        session_factory=session_factory,
        document_service=BrokenDocumentService(),
    )
    await processor.process(report_id)
    with session_factory() as session:
        report = ReportRepository(session).get(report_id)
        assert report.status == "failed"
        assert "synthetic extraction failure" in report.error_message
