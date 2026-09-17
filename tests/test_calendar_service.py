from datetime import date

from app.services.calendar_service import calendar_events


class ReportStub:
    def __init__(self, report_id=1, deleted=False):
        self.id = report_id
        self.report_date = date(2026, 8, 31)
        self.deleted_at = object() if deleted else None
        self.weekly_schedule = [
            {"day": "월(31)", "work": "사내 업무"},
            {"day": "화(01)", "work": "고령군청\n다이텍연구원"},
        ]
        self.author = "이동훈"
        self.department = "기술부"
        self.original_filename = "주간업무일지.pptx"


def test_calendar_events_resolve_cross_month_week_and_split_schedules():
    events = calendar_events([ReportStub()])
    assert [(item["date"].isoformat(), item["author"], item["schedule"]) for item in events] == [
        ("2026-08-31", "이동훈", "사내 업무"),
        ("2026-09-01", "이동훈", "고령군청"),
        ("2026-09-01", "이동훈", "다이텍연구원"),
    ]


def test_calendar_events_exclude_trash_and_apply_date_range():
    assert calendar_events([ReportStub(deleted=True)]) == []
    events = calendar_events([ReportStub()], start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert {item["date"] for item in events} == {date(2026, 9, 1)}
