from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

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


def test_report_list_searches_author_and_home_page(client, pptx_bytes):
    client.post(
        "/api/reports",
        files={"file": ("searchable.pptx", pptx_bytes, PPTX_MIME)},
        data={"author": "검색테스터", "department": "기술부", "report_date": "2026-08-31"},
    )
    response = client.get("/api/reports", params={"author": "검색테"})
    assert response.status_code == 200
    assert len(response.json()) == 1
    page = client.get("/", params={"keyword": "searchable"})
    assert page.status_code == 200
    assert "검색테스터" in page.text
    assert client.get("/", params={"report_date": ""}).status_code == 200
    assert client.get("/api/reports", params={"report_date": ""}).status_code == 200


def test_batch_upload_creates_team_group(client, pptx_bytes, session_factory):
    response = client.post(
        "/api/reports/batch",
        files=[
            ("files", ("one.pptx", pptx_bytes, PPTX_MIME)),
            ("files", ("two.pptx", pptx_bytes, PPTX_MIME)),
        ],
    )
    assert response.status_code == 202
    body = response.json()
    assert len(body["reports"]) == 2
    assert body["team_summary_url"].startswith("/team-summary/")
    team_page = client.get(body["team_summary_url"])
    assert team_page.status_code == 200
    assert "팀 주간업무 한눈에 보기" in team_page.text
    with session_factory() as session:
        reports = ReportRepository(session).list_batch(body["batch_id"])
        assert len(reports) == 2
        assert {report.original_filename for report in reports} == {"one.pptx", "two.pptx"}
        reports[0].weekly_schedule = [{"day": "월(31)", "work": "다이텍연구원"}]
        session.commit()
    team_page = client.get(body["team_summary_url"])
    assert "요일별 주요 일정" in team_page.text
    assert "다이텍연구원" in team_page.text


def test_batch_upload_rejects_more_than_ten_files(client, pptx_bytes):
    response = client.post(
        "/api/reports/batch",
        files=[("files", (f"{index}.pptx", pptx_bytes, PPTX_MIME)) for index in range(11)],
    )
    assert response.status_code == 400


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


def test_api_serializes_created_time_as_korea_time():
    from app.schemas import ReportListItem

    value = ReportListItem.model_validate({
        "id": 1, "report_date": None, "department": None, "author": None,
        "original_filename": "sample.pdf", "status": "completed",
        "created_at": datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc),
    }).model_dump(mode="json")
    assert value["created_at"].startswith("2026-09-02T09:00:00+09:00")
