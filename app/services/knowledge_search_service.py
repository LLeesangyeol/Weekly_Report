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
    "알려줘", "보여줘", "정리해줘", "요약해줘", "뭐", "무엇", "어떤", "관련", "대한",
    "있었냐", "있었어", "나온거", "나온", "여태까지", "지금까지", "문서", "내용", "해줘",
    "업무", "일정", "주요", "진행", "진행된", "진행한", "확인", "정리", "요약",
    "지난달", "이번달", "전달", "금월", "지난주", "이번주", "금주",
}

NO_EVIDENCE_ANSWER = "업로드된 문서에서 질문과 관련된 정보를 찾을 수 없습니다."
KOREAN_PARTICLE_SUFFIXES = ("으로", "에서", "에게", "한테", "부터", "까지", "처럼", "보다", "와", "과", "은", "는", "이", "가", "을", "를", "의", "에", "도")
LOOKUP_GENERIC_TERMS = {"문서", "파일", "업무일지", "주간업무일지", "작성", "작성한", "작성자", "찾아", "찾아줘", "찾기", "목록"}
SEARCH_ALIASES = {
    "취약점": ("보안", "보안문제", "보안이슈", "cve"),
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


def _meaningful_terms(query: str) -> list[str]:
    return [
        term for term in _expanded_search_terms(query)
        if term not in STOP_WORDS and term not in _date_terms(query) and not term.isdigit()
    ]


def _is_summary_query(query: str) -> bool:
    return any(value in query for value in ("요약", "정리", "묶어", "현황", "무엇을 했"))


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
    return any(value in query for value in ("찾아", "찾기", "목록", "문서", "파일", "작성한", "작성자"))


def _is_author_lookup_query(query: str) -> bool:
    return "작성한" in query or "작성자" in query


def _specific_lookup_terms(query: str) -> list[str]:
    return [term for term in _search_terms(query) if term not in LOOKUP_GENERIC_TERMS and len(term) >= 3]


def _date_terms(query: str) -> list[str]:
    result: list[str] = []
    for month, day in re.findall(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", query):
        result.extend((f"{int(month)}월 {int(day)}일", f"{int(month):02d}-{int(day):02d}"))
    iso = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", query)
    result.extend(value.replace(".", "-").replace("/", "-") for value in iso)
    return result


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


def _snippet(text: str, terms: list[str], length: int = 420) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    positions = [normalized.casefold().find(term) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - 55)
    value = normalized[start:start + length]
    return ("…" if start else "") + value + ("…" if start + length < len(normalized) else "")


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
    lines = [f"{date_label} 관련 업무일지 {len(hits)}개를 확인했습니다."]
    for source_number, hit in enumerate(hits, 1):
        report = hit.report
        structured = report.structured_json or {}
        completed = _structured_items(structured.get("completed_work"))
        schedule = _structured_items(structured.get("weekly_schedule"))
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
        requested_month = _requested_month(query)
        hits: list[SearchHit] = []
        for report in self.repository.list(limit=500):
            if report.status != ReportStatus.COMPLETED.value:
                continue
            if requested_month and (not report.report_date or (report.report_date.year, report.report_date.month) != requested_month):
                continue
            text = _report_text(report)
            matched = [term for term in terms if _matches_term(term, text)]
            matched_meaningful = [term for term in meaningful_terms if _matches_term(term, text)]
            matched_dates = [term for term in date_terms if _matches_term(term, text)]
            if meaningful_terms and not date_terms and not matched_meaningful:
                continue
            if not matched and not matched_dates:
                continue
            score = sum(3 if _matches_term(term, report.original_filename) else 1 for term in matched_meaningful)
            score += len(matched_dates) * 2
            hits.append(SearchHit(report, _snippet(text, matched + matched_dates), float(score)))
        return sorted(hits, key=lambda hit: (hit.score, hit.report.created_at), reverse=True)[:limit]

    async def answer(self, query: str, limit: int) -> tuple[str, list[SearchHit], str]:
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
                    if report is None:
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
        if date_query:
            return _date_work_summary(query, hits), hits, "date_summary"
        personal_leave = _personal_leave_fallback(query, hits)
        if personal_leave:
            return personal_leave[0], personal_leave[1], "search"
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
        llm_hits = hits[:5]
        context = "\n\n".join(
            f"[문서 {index}] {hit.report.original_filename}\n"
            f"작성자: {hit.report.author or '-'}\n부서: {hit.report.department or '-'}\n"
            f"기준일: {hit.report.report_date or '-'}\n{hit.snippet}"
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
                answer = answer.rstrip() + "\n\n근거 문서: " + ", ".join(
                    f"[문서 {index}]" for index in range(1, min(len(hits), 5) + 1)
                )
                return answer, hits[:5], "llm"
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
