from __future__ import annotations

from pathlib import Path

from app.repositories.report_repository import ReportRepository


PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_upload_api_creates_record(client, pptx_bytes, session_factory):
    response = client.post(
        "/api/reports",
        files={"file": ("weekly.pptx", pptx_bytes, PPTX_MIME)},
        data={"author": "홍길동", "department": "기술부", "report_date": "2026-08-31"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    with session_factory() as session:
        report = ReportRepository(session).get(body["id"])
        assert report.author == "홍길동"
        assert report.stored_filename != "weekly.pptx"


def test_get_missing_report_returns_404(client):
    assert client.get("/api/reports/999999").status_code == 404


def test_disguised_upload_returns_400(client):
    response = client.post(
        "/api/reports",
        files={"file": ("fake.pdf", b"plain text", "application/pdf")},
    )
    assert response.status_code == 400


def test_unsafe_download_path_is_blocked(client, session_factory, settings, tmp_path: Path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7\n")
    with session_factory() as session:
        report = ReportRepository(session).create(
            original_filename="outside.pdf",
            stored_filename="11111111-1111-1111-1111-111111111111.pdf",
            file_path=str(outside),
            file_size=outside.stat().st_size,
            content_type="application/pdf",
            source_type="pdf",
            model_name="test-model",
        )
        report_id = report.id
    response = client.get(f"/api/reports/{report_id}/download")
    assert response.status_code == 403


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}
