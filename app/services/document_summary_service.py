"""Deterministic summaries for heading-based internal procedure documents."""
from __future__ import annotations

import re

from app.services.vulnerability_summary_service import summarize_vulnerability_report


def _clean(value: str) -> str:
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"[*_]+", "", value)
    return re.sub(r"\s+", " ", value).strip(" -:")


def summarize_heading_document(text: str) -> str | None:
    """Summarize numbered Markdown-style headings without asking a small LLM to infer layout."""
    headings = list(re.finditer(r"(?:^|\n)\s*#{2,6}\s*(?:\d+\.\s*)?([^\n#]+)", text))
    if len(headings) < 2:
        return None
    entries: list[str] = []
    log_entries: list[str] = []
    for index, heading in enumerate(headings):
        title = _clean(heading.group(1))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = _clean(text[heading.end():end])
        logs = [_clean(value) for value in re.findall(r"로그\s*:\s*`?\[?([^\]`\n]+)\]?`?", body)]
        if title and not any(label in title for label in ("로그 확인", "예시")):
            action = re.split(r"로그\s*:", body, maxsplit=1)[0].strip()
            entries.append(f"{title}: {action or '설정 상태를 확인'}")
        log_entries.extend(logs)
    entries = list(dict.fromkeys(entry for entry in entries if entry))
    log_entries = list(dict.fromkeys(entry for entry in log_entries if entry))
    if not entries:
        return None
    lines = ["## 문서 핵심 항목", *(f"- {entry}" for entry in entries[:10])]
    if log_entries:
        lines.extend(["## 확인 로그", *(f"- [{entry}]" for entry in log_entries[:12])])
    return "\n".join(lines)


def summarize_structured_document(text: str) -> str | None:
    """One reusable structural layer for every parsed format.

    It recognizes repeated field tables, headings and lists independent of a
    filename, customer or individual template.  Free-form prose falls through
    to the LLM, which remains a fallback rather than the primary parser.
    """
    if table_summary := summarize_vulnerability_report(text):
        return table_summary
    if heading_summary := summarize_heading_document(text):
        return heading_summary
    bullets = [
        _clean(value)
        for value in re.findall(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+([^\n]+)", text)
    ]
    bullets = list(dict.fromkeys(value for value in bullets if len(value) >= 8))
    if len(bullets) >= 3:
        return "\n".join(["## 핵심 항목", *(f"- {value}" for value in bullets[:12])])
    return None
