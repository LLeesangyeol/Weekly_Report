from __future__ import annotations

import re

from app.schemas import StructuredReport


_SECTION_MARKERS = (
    "[금주 예정 업무]",
    "[주간 일정 계획표]",
    "[금주 업무 실적]",
)


def _section(text: str, start: str, end: str | None = None) -> str:
    _, found, remainder = text.partition(start)
    if not found:
        return ""
    return remainder.partition(end)[0] if end else remainder


def _clean_item(value: str) -> str:
    lines = []
    for line in value.splitlines():
        line = line.strip()
        if (
            not line
            or re.fullmatch(r"\[사내\s*업무\]", line)
            or line.startswith("[예정 업무 영역")
            or line.startswith("[실적 업무 영역")
        ):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _work_blocks(value: str) -> list[str]:
    """Keep each blank-line-delimited customer/work block, with or without bullets."""
    result: list[str] = []
    for block in re.split(r"\n\s*\n", value):
        # Some authors put multiple bullet tasks into one cell without blank lines.
        candidates = re.split(r"(?m)^\s*[▪•]\s*", block)
        for candidate in candidates:
            cleaned = _clean_item(candidate)
            if cleaned:
                result.append(cleaned)
    return result


def _first_match(pattern: str, text: str) -> str | None:
    matched = re.search(pattern, text, flags=re.MULTILINE)
    return matched.group(1).strip() if matched else None


def parse_weekly_report_template(text: str) -> StructuredReport | None:
    """Parse the approved one-page Korean weekly-report form without LLM guessing."""
    if not all(marker in text for marker in _SECTION_MARKERS):
        return None

    planned_text = _section(text, "[금주 예정 업무]", "[주간 일정 계획표]")
    schedule_text = _section(text, "[주간 일정 계획표]", "[금주 업무 실적]")
    completed_text = _section(text, "[금주 업무 실적]")
    schedule = []
    for day, work in re.findall(r"(?m)^\s*-\s*([^:\n]+):\s*(.+?)\s*$", schedule_text):
        schedule.append({"day": day.strip(), "work": work.strip()})

    return StructuredReport(
        report_date=_first_match(r"(?m)^(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)\s*$", text),
        department=_first_match(r"(?m)^부\s*서:\s*(.+)$", text),
        author=_first_match(r"(?m)^성\s*명:\s*(.+)$", text),
        planned_work=_work_blocks(planned_text),
        completed_work=_work_blocks(completed_text),
        weekly_schedule=schedule,
        issues=[],
        next_week_plan=[],
    )
