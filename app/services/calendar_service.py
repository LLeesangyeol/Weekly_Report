from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Iterable

from app.models import Report


WEEKDAY_INDEX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
DAY_PATTERN = re.compile(r"([월화수목금토일])\s*\(\s*(\d{1,2})\s*\)")


def _schedule_date(report_date: date, day_label: str) -> date | None:
    matched = DAY_PATTERN.search(day_label)
    if not matched:
        return None
    weekday, day_number = matched.group(1), int(matched.group(2))
    expected_weekday = WEEKDAY_INDEX[weekday]
    week_start = report_date - timedelta(days=report_date.weekday())
    expected = week_start + timedelta(days=expected_weekday)
    if expected.day == day_number:
        return expected

    # Some files use a publication date rather than the Monday date. Resolve the
    # nearest matching calendar day without guessing across a distant month.
    candidates = [
        report_date + timedelta(days=offset)
        for offset in range(-14, 15)
        if (report_date + timedelta(days=offset)).day == day_number
        and (report_date + timedelta(days=offset)).weekday() == expected_weekday
    ]
    return min(candidates, key=lambda value: abs((value - report_date).days)) if candidates else None


def _schedule_rows(value: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        day_label = str(item.get("day") or "").strip()
        work = str(item.get("work") or item.get("schedule") or "").strip()
        if not day_label or not work or work in {"내용 없음", "없음", "-"}:
            continue
        for line in (part.strip(" -•\t") for part in work.splitlines()):
            if line:
                yield day_label, line


def calendar_events(
    reports: Iterable[Report],
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[int, date, str]] = set()
    for report in reports:
        if report.deleted_at is not None or report.report_date is None:
            continue
        for day_label, schedule in _schedule_rows(report.weekly_schedule):
            event_date = _schedule_date(report.report_date, day_label)
            if event_date is None or (start and event_date < start) or (end and event_date > end):
                continue
            key = (report.id, event_date, schedule)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "report_id": report.id,
                "date": event_date,
                "author": report.author or "작성자 미지정",
                "department": report.department,
                "schedule": schedule,
                "original_filename": report.original_filename,
            })
    return sorted(events, key=lambda item: (item["date"], item["author"], item["schedule"]))
