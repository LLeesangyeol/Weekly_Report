from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import Report, ReportStatus
from app.repositories.report_repository import ReportRepository
from app.services.ollama_service import OllamaError, OllamaService
from app.services.vector_store_service import VectorStoreService


STOP_WORDS = {
    "알려줘", "보여줘", "정리해줘", "요약해줘", "뭐", "무엇", "어떤", "관련", "관련된", "대한",
    "있었냐", "있었어", "나온거", "나온", "여태까지", "지금까지", "문서", "내용", "해줘",
    "업무", "일정", "주요", "진행", "진행된", "진행한", "확인", "정리", "요약",
    "지난달", "이번달", "전달", "금월", "지난주", "이번주", "금주",
    "현재", "지금", "전체", "총", "몇개", "몇건", "몇", "개수", "건수", "있는지", "있냐", "있나요",
    "했어", "했냐", "했나요", "하는지", "알고싶어", "궁금해",
    "누가", "누구", "사람", "발견된", "발견한", "날짜별", "날짜별로",
    "뭐야", "뭔가", "완료한", "완료된", "완료했는지",
}

NO_EVIDENCE_ANSWER = "업로드된 문서에서 질문과 관련된 정보를 찾을 수 없습니다."
KOREAN_PARTICLE_SUFFIXES = ("으로", "에서", "에게", "한테", "부터", "까지", "처럼", "보다", "와", "과", "은", "는", "이", "가", "을", "를", "의", "에", "도")
LOOKUP_GENERIC_TERMS = {"문서", "파일", "업무일지", "주간업무일지", "작성", "작성한", "작성자", "찾아", "찾아줘", "찾기", "목록"}
SEARCH_ALIASES = {
    # Generic "보안" appears in many unrelated weekly tasks, so do not expand
    # a precise vulnerability query into that broad term.
    "취약점": ("보안취약점", "보안문제", "보안이슈", "cve", "vulnerability"),
    "보안": ("취약점", "cve", "보안문제", "보안이슈"),
    "휴가": ("연차", "반차", "휴무"),
    "연차": ("휴가", "반차", "휴무"),
    "반차": ("휴가", "연차", "휴무"),
    "예정": ("계획", "차주"),
    "계획": ("예정", "차주"),
    "완료": ("실적", "수행", "진행"),
    "문제": ("이슈", "장애", "오류", "위험", "지원"),
    "교육": ("강의", "세미나", "훈련"),
}


@dataclass(slots=True)
class SearchHit:
    report: Report
    snippet: str
    score: float
    page_number: int | None = None
    heading: str | None = None


def _search_terms(query: str) -> list[str]:
    values = re.findall(r"[가-힣A-Za-z0-9_.-]{2,}", query.casefold())
    terms: list[str] = []
    for value in values:
        if value in STOP_WORDS:
            continue
        terms.append(value)
        if re.fullmatch(r"[가-힣]+", value):
            for suffix in KOREAN_PARTICLE_SUFFIXES:
                if value.endswith(suffix) and len(value) - len(suffix) >= 2:
                    terms.append(value[:-len(suffix)])
                    break
    return list(dict.fromkeys(terms))


def _expanded_search_terms(query: str) -> list[str]:
    terms = _search_terms(query)
    for term in tuple(terms):
        terms.extend(SEARCH_ALIASES.get(term, ()))
    return list(dict.fromkeys(terms))


def _core_query_terms(query: str) -> list[str]:
    """Return user concepts without aliases or grammatical particles."""
    values = re.findall(r"[가-힣A-Za-z0-9_.-]{2,}", query.casefold())
    terms: list[str] = []
    for value in values:
        normalized = value
        if re.fullmatch(r"[가-힣]+", value):
            for suffix in KOREAN_PARTICLE_SUFFIXES:
                if value.endswith(suffix) and len(value) - len(suffix) >= 2:
                    normalized = value[:-len(suffix)]
                    break
        if normalized in STOP_WORDS or normalized in LOOKUP_GENERIC_TERMS or normalized.isdigit():
            continue
        terms.append(normalized)
    return list(dict.fromkeys(terms))


def _meaningful_terms(query: str) -> list[str]:
    return [
        term for term in _expanded_search_terms(query)
        if term not in STOP_WORDS
        and term not in LOOKUP_GENERIC_TERMS
        and term not in _date_terms(query)
        and not term.isdigit()
    ]


def _is_summary_query(query: str) -> bool:
    return any(value in query for value in ("요약", "정리", "묶어", "현황", "무엇을 했"))


def _is_direct_fact_query(query: str) -> bool:
    return any(value in query for value in (
        "누가", "누구", "언제", "어디", "어느", "무엇", "뭐", "사람", "담당자", "작성자",
    ))


def _is_inventory_query(query: str) -> bool:
    compact = re.sub(r"\s+", "", query.casefold())
    count_words = ("몇개", "몇건", "개수", "건수", "총몇", "몇명이", "몇명")
    status_summary = "현황" in compact and any(
        value in compact for value in ("업무일지", "전체문서", "문서함", "색인", "검색준비")
    )
    return any(word in compact for word in count_words) or status_summary


def _is_weekly_report(report: Report) -> bool:
    # Match the product's 업무일지 tab classification exactly.
    return report.source_type.casefold() in {"ppt", "pptx"}


def _inventory_answer(query: str, reports: list[Report], trashed: list[Report]) -> str:
    compact = re.sub(r"\s+", "", query.casefold())
    if "휴지통" in compact:
        return f"현재 휴지통에는 문서가 총 {len(trashed)}개 있습니다."
    if "작성자" in compact or "몇명" in compact:
        authors = sorted({report.author.strip() for report in reports if report.author and _is_weekly_report(report)})
        return f"현재 업무일지 작성자는 총 {len(authors)}명입니다." + (f"\n\n- {', '.join(authors)}" if authors else "")
    if "취약점" in compact:
        count = sum(_is_vulnerability_report(report) for report in reports)
        return f"현재 휴지통을 제외한 취약점 문서는 총 {count}개입니다."
    if "업무일지" in compact or "주간일지" in compact:
        count = sum(_is_weekly_report(report) for report in reports)
        return f"현재 휴지통을 제외한 업무일지는 총 {count}개입니다."
    if "색인" in compact or "검색준비" in compact:
        count = sum(report.index_status == "indexed" for report in reports)
        return f"현재 AI 검색 준비가 완료된 문서는 총 {count}개입니다. 전체 문서는 {len(reports)}개입니다."
    if "실패" in compact or "오류" in compact:
        count = sum(report.status == "failed" or report.index_status == "failed" for report in reports)
        return f"현재 처리 또는 색인에 실패한 문서는 총 {count}개입니다."
    return f"현재 휴지통을 제외한 전체 문서는 총 {len(reports)}개입니다."


def _is_vulnerability_findings_query(query: str) -> bool:
    """Distinguish a vulnerability finding from a weekly task merely mentioning security."""
    return "취약점" in query and any(value in query for value in ("발견", "점검", "결과", "조치", "목록", "정리", "현황"))


def _is_vulnerability_report(report: Report) -> bool:
    filename = report.original_filename or ""
    text = _report_text(report)
    return "취약점" in filename or ("점검 내용" in text and "점검 결과" in text and "조치 내용" in text)


def _compact(value: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", value.casefold())


def _matches_term(term: str, text: str) -> bool:
    folded = text.casefold()
    if term in folded or _compact(term) in _compact(text):
        return True
    if len(term) < 3:
        return False
    return any(
        SequenceMatcher(None, term, token).ratio() >= 0.82
        for token in re.findall(r"[가-힣A-Za-z0-9_.-]{3,}", folded)
    )


def _is_document_lookup_query(query: str) -> bool:
    explicit = any(value in query for value in ("찾아", "찾기", "목록", "작성한", "작성자"))
    file_list = any(value in query for value in ("문서", "파일")) and "보여" in query
    weekly_list = "업무일지" in query and any(value in query for value in ("보여", "목록", "찾아"))
    return explicit or file_list or weekly_list


def _is_author_lookup_query(query: str) -> bool:
    return "작성한" in query or "작성자" in query


def _specific_lookup_terms(query: str) -> list[str]:
    return [term for term in _search_terms(query) if term not in LOOKUP_GENERIC_TERMS and len(term) >= 3]


def _date_terms(query: str) -> list[str]:
    result: list[str] = []
    for month, day in re.findall(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", query):
        result.extend((f"{int(month)}월 {int(day)}일", f"{int(month):02d}-{int(day):02d}", f"{int(day)}일"))
    # Weekly reports commonly label a row as 월(31), so accept a day-only question too.
    for day in re.findall(r"(?<!\d)(\d{1,2})\s*일", query):
        result.append(f"{int(day)}일")
    iso = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", query)
    result.extend(value.replace(".", "-").replace("/", "-") for value in iso)
    return result


def _requested_day_numbers(query: str) -> set[int]:
    values = re.findall(r"(?<!\d)(\d{1,2})\s*일", query)
    return {int(value) for value in values if 1 <= int(value) <= 31}


def _day_matches(value: object, requested_days: set[int]) -> bool:
    if not requested_days or not value:
        return False
    text = str(value)
    numbers = {int(number) for number in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text)}
    return bool(numbers & requested_days)


def _items_for_requested_days(value: object, requested_days: set[int]) -> list[str]:
    if not requested_days:
        return _structured_items(value)
    if not isinstance(value, list):
        return []
    filtered: list[str] = []
    for item in value:
        if isinstance(item, dict) and _day_matches(item.get("day"), requested_days):
            filtered.extend(_structured_items([item]))
    return filtered


def _has_requested_day_content(report: Report, requested_days: set[int]) -> bool:
    if not requested_days:
        return True
    structured = report.structured_json or {}
    return any(
        _items_for_requested_days(structured.get(field), requested_days)
        for field in ("completed_work", "planned_work", "weekly_schedule")
    )


def _requested_month(query: str) -> tuple[int, int] | None:
    today = date.today()
    if "지난달" in query or "전달" in query:
        return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    if "이번달" in query or "금월" in query:
        return today.year, today.month
    return None


def _has_keyword_evidence(query: str, report: Report) -> bool:
    """Only admit semantic-only matches when the document has a concrete query anchor."""
    anchors = [term for term in _expanded_search_terms(query) if term not in STOP_WORDS and not term.isdigit()]
    if not anchors:
        return False
    text = _report_text(report)
    return any(_matches_term(term, text) for term in anchors)


def _report_text(report: Report) -> str:
    structured = json.dumps(report.structured_json or {}, ensure_ascii=False)
    return "\n".join(filter(None, (
        report.original_filename, report.author, report.department,
        report.extracted_text, report.summary, structured,
        report.report_date.isoformat() if report.report_date else None,
    )))


def _snippet(text: str, terms: list[str], length: int = 620) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    folded = normalized.casefold()
    positions = [folded.find(term.casefold()) for term in terms if term]
    positions = sorted({position for position in positions if position >= 0})[:2]
    if not positions:
        return normalized[:length] + ("…" if len(normalized) > length else "")
    windows: list[str] = []
    for position in positions:
        start = max(0, position - 180)
        end = min(len(normalized), position + length - 180)
        value = ("…" if start else "") + normalized[start:end] + ("…" if end < len(normalized) else "")
        if not windows or value != windows[-1]:
            windows.append(value)
    return "\n\n".join(windows)


def _evidence_fallback(query: str, hits: list[SearchHit]) -> str:
    lines = [f"질문과 관련된 문서 {len(hits)}개를 확인했습니다."]
    for index, hit in enumerate(hits, 1):
        report = hit.report
        label = report.author or report.original_filename
        if report.report_date:
            label = f"{label} · {report.report_date.isoformat()}"
        lines.append(f"## {label}")
        structured = report.structured_json or {}
        report_text = _report_text(report)
        terms = [
            term for term in _expanded_search_terms(query)
            if term not in STOP_WORDS and _matches_term(term, report_text)
        ]
        shown = 0
        for field, field_label in (("completed_work", "완료 업무"), ("planned_work", "예정 업무"), ("weekly_schedule", "주요 일정")):
            matching = [item for item in _structured_items(structured.get(field)) if not terms or any(_matches_term(term, item) for term in terms)]
            if matching:
                lines.append(f"- {field_label}: {' / '.join(matching[:2])} [문서 {index}]")
                shown += 1
        if not shown:
            lines.append(f"- 관련 내용: {_snippet(hit.snippet, [], length=220)} [문서 {index}]")
    return "\n".join(lines)


def _direct_fact_answer(query: str, hits: list[SearchHit]) -> str:
    terms = _core_query_terms(query)
    lines = [f"문서에서 직접 확인된 결과 {len(hits)}건입니다."]
    for source_number, hit in enumerate(hits, 1):
        report = hit.report
        label = report.author or report.original_filename
        if report.report_date:
            label += f" · {report.report_date.isoformat()}"
        structured = report.structured_json or {}
        candidates: list[str] = []
        for field in ("completed_work", "planned_work", "weekly_schedule"):
            candidates.extend(_structured_items(structured.get(field)))
        matching = [
            item for item in candidates
            if not terms or any(
                _matches_term(variant, item)
                for term in terms for variant in (term, *SEARCH_ALIASES.get(term, ()))
            )
        ]
        evidence = " / ".join(matching[:2]) if matching else _snippet(hit.snippet, terms, length=300)
        lines.append(f"- {label}: {evidence} [문서 {source_number}]")
    return "\n".join(lines)


def _personal_leave_fallback(query: str, hits: list[SearchHit]) -> tuple[str, list[SearchHit]] | None:
    asks_for_person = any(value in query for value in ("누가", "누구", "사람", "작성자"))
    asks_for_leave = any(value in query for value in ("휴가", "연차", "반차", "휴무"))
    if not asks_for_person or not asks_for_leave:
        return None
    personal_hits = [
        hit for hit in hits
        if hit.report.author
        and re.search(r"(?:연차|반차|휴무|(?<!시스템\s)휴가)", hit.snippet)
        and not re.search(r"하계휴가\s*시스템", hit.snippet)
    ]
    if not personal_hits:
        return None
    lines = ["휴가·연차 관련 내용이 확인된 업무일지 작성자입니다."]
    for source_number, hit in enumerate(personal_hits, 1):
        lines.append(f"- {hit.report.author.strip()}: {hit.snippet} [문서 {source_number}]")
    return "\n".join(lines), personal_hits


def _structured_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        elif isinstance(item, dict):
            values = [str(item[key]).strip() for key in ("day", "work", "schedule", "content") if item.get(key)]
            if values:
                items.append(" · ".join(dict.fromkeys(values)))
    return items


def _date_work_summary(query: str, hits: list[SearchHit]) -> str:
    """Return every matching report deterministically; small models often cite only one source."""
    date_label = _date_terms(query)[0] if _date_terms(query) else "해당 날짜"
    requested_days = _requested_day_numbers(query)
    lines = [f"{date_label} 관련 업무일지 {len(hits)}개를 확인했습니다."]
    undated_completed_reports = 0
    for source_number, hit in enumerate(hits, 1):
        report = hit.report
        structured = report.structured_json or {}
        completed = _items_for_requested_days(structured.get("completed_work"), requested_days)
        schedule = _items_for_requested_days(structured.get("weekly_schedule"), requested_days)
        if requested_days and _structured_items(structured.get("completed_work")) and not completed:
            undated_completed_reports += 1
        label = report.author or report.original_filename
        if report.department:
            label = f"{label} · {report.department}"
        lines.append(f"## {label}")
        if completed:
            lines.append(f"- 진행 업무: {' / '.join(completed)} [문서 {source_number}]")
        if schedule:
            lines.append(f"- 주요 일정: {' / '.join(schedule)} [문서 {source_number}]")
        if not completed and not schedule:
            lines.append(f"- 문서 내용: {hit.snippet} [문서 {source_number}]")
    if undated_completed_reports:
        lines.append(
            f"\n※ {undated_completed_reports}개 업무일지의 완료 업무는 요일별로 기록되지 않아 "
            f"{date_label} 업무로 단정하지 않고 제외했습니다."
        )
    return "\n".join(lines)


def _vulnerability_findings_summary(hits: list[SearchHit]) -> str:
    lines = [f"실제 취약점 점검 결과 문서 {len(hits)}개를 확인했습니다."]
    for source_number, hit in enumerate(hits, 1):
        report = hit.report
        when = report.report_date.isoformat() if report.report_date else "날짜 미지정"
        lines.append(f"## {when} · {report.original_filename}")
        summary_lines = [line.strip() for line in (report.summary or "").splitlines() if line.strip()]
        # The dedicated report summary has already selected point/result/action fields.
        visible = [line for line in summary_lines if not line.startswith("## 점검 개요")][:10]
        if visible:
            lines.extend(visible)
        else:
            lines.append(f"- 관련 점검 내용: {_snippet(hit.snippet, ['점검 내용', '조치 내용'], length=420)}")
        lines.append(f"[문서 {source_number}]")
    return "\n".join(lines)


class KnowledgeSearchService:
    """Keyword-first retrieval boundary ready to be replaced by Qdrant hybrid search."""

    def __init__(
        self,
        session: Session,
        ollama: OllamaService,
        vector_store: VectorStoreService | None = None,
        *,
        min_semantic_score: float = 0.68,
    ):
        self.repository = ReportRepository(session)
        self.ollama = ollama
        self.vector_store = vector_store
        self.min_semantic_score = min_semantic_score

    def retrieve(self, query: str, limit: int) -> list[SearchHit]:
        terms = _expanded_search_terms(query)
        meaningful_terms = _meaningful_terms(query)
        date_terms = _date_terms(query)
        requested_days = _requested_day_numbers(query)
        requested_month = _requested_month(query)
        vulnerability_findings = _is_vulnerability_findings_query(query)
        weekly_date_query = bool(date_terms) and any(value in query for value in ("업무", "일정", "업무일지")) and "취약점" not in query
        core_terms = [] if date_terms else _core_query_terms(query)
        hits: list[SearchHit] = []
        for report in self.repository.list(limit=500):
            if report.status != ReportStatus.COMPLETED.value:
                continue
            if vulnerability_findings and not _is_vulnerability_report(report):
                continue
            if weekly_date_query and not _is_weekly_report(report):
                continue
            if requested_month and (not report.report_date or (report.report_date.year, report.report_date.month) != requested_month):
                continue
            text = _report_text(report)
            matched = [term for term in terms if _matches_term(term, text)]
            matched_meaningful = [term for term in meaningful_terms if _matches_term(term, text)]
            matched_dates = [
                term for term in date_terms
                if _matches_term(term, text)
                or (term.endswith("일") and _has_requested_day_content(report, requested_days))
            ]
            matched_core = [
                term for term in core_terms
                if any(_matches_term(variant, text) for variant in (term, *SEARCH_ALIASES.get(term, ())))
            ]
            minimum_core_matches = 1 if len(core_terms) <= 1 else (len(core_terms) * 2 + 2) // 3
            if core_terms and len(matched_core) < minimum_core_matches:
                continue
            if meaningful_terms and not date_terms and not matched_meaningful:
                continue
            if not matched and not matched_dates:
                continue
            score = sum(5 if _matches_term(term, report.original_filename) else 2 for term in matched_core)
            score += sum(2 if _matches_term(term, report.original_filename) else 1 for term in matched_meaningful)
            score += len(matched_dates) * 2
            hits.append(SearchHit(report, _snippet(text, matched + matched_dates), float(score)))
        return sorted(hits, key=lambda hit: (hit.score, hit.report.created_at), reverse=True)[:limit]

    async def answer(self, query: str, limit: int) -> tuple[str, list[SearchHit], str]:
        all_reports = self.repository.list(limit=None, include_deleted=True)
        active_reports = [report for report in all_reports if report.deleted_at is None]
        trashed_reports = [report for report in all_reports if report.deleted_at is not None]
        if _is_inventory_query(query):
            return _inventory_answer(query, active_reports, trashed_reports), [], "inventory"
        date_query = bool(_date_terms(query))
        hits = self.retrieve(query, max(limit, 10) if date_query else limit)
        # Keyword/metadata hits are both faster and more precise for internal documents.
        # Use vector search only as a fallback when no concrete match was found.
        if self.vector_store is not None and not hits:
            try:
                query_vector = (await self.ollama.embed([query]))[0]
                semantic = self.vector_store.search(query_vector, limit=max(limit * 2, 12))
                merged: dict[int, SearchHit] = {hit.report.id: hit for hit in hits}
                for item in semantic:
                    if item.score < self.min_semantic_score:
                        continue
                    report = self.repository.get(item.report_id)
                    if report is None or report.deleted_at is not None or report.status != ReportStatus.COMPLETED.value:
                        continue
                    dates = _date_terms(query)
                    if dates and not any(value.casefold() in _report_text(report).casefold() for value in dates):
                        continue
                    if not _has_keyword_evidence(query, report) and item.score < max(self.min_semantic_score + 0.12, 0.65):
                        continue
                    candidate = SearchHit(report, _snippet(item.content, _expanded_search_terms(query)), item.score * 4, item.page_number, item.heading)
                    existing = merged.get(report.id)
                    if existing:
                        existing.score += candidate.score
                        if candidate.score > existing.score / 2:
                            existing.snippet = candidate.snippet
                    else:
                        merged[report.id] = candidate
                hits = sorted(merged.values(), key=lambda item: item.score, reverse=True)[:limit]
            except OllamaError:
                pass
        if _is_author_lookup_query(query):
            specific_terms = _specific_lookup_terms(query)
            author_hits = [
                hit for hit in hits
                if any(
                    term in f"{hit.report.author or ''} {hit.report.original_filename}".casefold()
                    for term in specific_terms
                )
            ]
            if author_hits:
                hits = author_hits
        if not hits:
            return NO_EVIDENCE_ANSWER, [], "no_results"
        if _is_vulnerability_findings_query(query):
            return _vulnerability_findings_summary(hits), hits, "vulnerability_summary"
        if date_query:
            requested_days = _requested_day_numbers(query)
            if requested_days:
                hits = [hit for hit in hits if _has_requested_day_content(hit.report, requested_days)]
                if not hits:
                    return NO_EVIDENCE_ANSWER, [], "no_results"
            return _date_work_summary(query, hits), hits, "date_summary"
        personal_leave = _personal_leave_fallback(query, hits)
        if personal_leave:
            return personal_leave[0], personal_leave[1], "search"
        if _is_direct_fact_query(query):
            return _direct_fact_answer(query, hits), hits, "direct_fact"
        if _is_document_lookup_query(query):
            lines = [f"질문과 일치하는 문서 {len(hits)}개를 찾았습니다."]
            for hit in hits:
                report = hit.report
                detail = " · ".join(filter(None, (
                    report.author,
                    report.department,
                    report.report_date.isoformat() if report.report_date else None,
                )))
                lines.append(f"- {report.original_filename}" + (f" ({detail})" if detail else ""))
            return "\n".join(lines), hits, "search"
        if _is_summary_query(query) and _meaningful_terms(query):
            return _evidence_fallback(query, hits), hits, "structured_summary"
        llm_hits = hits[:6]
        context = "\n\n".join(
            f"[문서 {index}] {hit.report.original_filename}\n"
            f"작성자: {hit.report.author or '-'}\n부서: {hit.report.department or '-'}\n"
            f"기준일: {hit.report.report_date or '-'}\n{hit.snippet[:460]}"
            for index, hit in enumerate(llm_hits, 1)
        )
        try:
            answer = (await self.ollama.answer_from_sources(query, context)).strip()
            refusal_markers = (
                "[근거 없음]", "관련된 정보를 찾을 수 없", "문서에서 찾을 수 없",
                "확인할 수 없", "알 수 없", "아마", "추정", "추측", "가능성",
            )
            citations = [int(value) for value in re.findall(r"\[문서\s+(\d+)\]", answer)]
            if not answer or any(marker in answer for marker in refusal_markers):
                fallback = _personal_leave_fallback(query, hits)
                if fallback:
                    return fallback[0], fallback[1], "search_fallback"
                return _evidence_fallback(query, hits), hits, "search_fallback"
            if not citations:
                # Never attach arbitrary citations to an unsupported model claim.
                return _evidence_fallback(query, hits), hits, "search_fallback"
            if any(number < 1 or number > len(llm_hits) for number in citations):
                return _evidence_fallback(query, hits), hits, "search_fallback"
            cited_hits = [llm_hits[number - 1] for number in dict.fromkeys(citations)]
            return answer, cited_hits, "llm"
        except OllamaError:
            lines = [f"검색된 문서는 총 {len(hits)}개입니다."]
            for hit in hits[:5]:
                when = hit.report.report_date.isoformat() if hit.report.report_date else "날짜 미지정"
                lines.append(f"- {when} · {hit.report.original_filename}: {hit.snippet}")
            lines.append("\n현재 AI 모델에 연결되지 않아 검색 결과를 원문 중심으로 표시했습니다.")
            return "\n".join(lines), hits, "search_fallback"
