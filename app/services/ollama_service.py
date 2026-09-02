from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.schemas import StructuredReport


class OllamaError(RuntimeError):
    pass


class OllamaConnectionError(OllamaError):
    pass


class OllamaTimeoutError(OllamaError):
    pass


class OllamaModelNotFoundError(OllamaError):
    pass


class OllamaResponseError(OllamaError):
    pass


class OllamaJsonError(OllamaError):
    pass


_llm_semaphore = asyncio.Semaphore(1)


def parse_json_response(content: str) -> dict[str, Any]:
    value = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise OllamaJsonError("LLM 응답에서 JSON 객체를 찾을 수 없습니다.")
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OllamaJsonError("LLM 응답 JSON을 파싱할 수 없습니다.") from exc
    if not isinstance(parsed, dict):
        raise OllamaJsonError("LLM 응답은 JSON 객체여야 합니다.")
    return parsed


def split_text(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    blocks = re.split(r"(?=--- (?:Slide|Page) \d+ ---)|\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for block in (part.strip() for part in blocks if part.strip()):
        if len(block) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(block), chunk_size):
                chunks.append(block[start : start + chunk_size])
        elif current and len(current) + len(block) + 2 > chunk_size:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        chunks.append(current)
    return chunks


def _deduplicate(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True).strip().casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


STRUCTURE_SYSTEM_PROMPT = """당신은 사내 주간업무일지 구조화 도우미다.
문서에 실제로 있는 정보만 사용하고 추측하거나 새 사실을 만들지 마라.
예정 업무와 실적 업무를 구분하고, 내용이 없으면 빈 배열을 사용하라.
특히 '[금주 예정 업무]' 아래 내용은 planned_work에만, '[금주 업무 실적]' 아래 내용은 completed_work에만 넣어라.
각 업무 영역의 모든 글머리표와 하위 항목을 빠뜨리지 말고 하나의 업무 객체 또는 문자열에 함께 보존하라.
'[주간 일정 계획표]'은 weekly_schedule에 요일과 계획을 함께 보존하라.
결재란, 매출·목표·현재·진행률 같은 빈 서식 항목은 업무로 만들지 마라.
next_week_plan은 문서에 차주 계획이 명시된 경우에만 채워라. 금주 예정 업무를 차주 계획으로 옮기지 마라.
issues는 명시된 문제·차질·지원 필요사항만 넣고, 없으면 빈 배열을 반환하라.
반드시 아래 키를 모두 가진 JSON 객체만 출력하라. 마크다운이나 설명을 붙이지 마라.
report_date, department, author, planned_work, completed_work, weekly_schedule, issues, next_week_plan"""

SUMMARY_HEADINGS = (
    "## 금주 완료 업무",
    "## 진행 중인 업무",
    "## 문제점 및 지원 필요사항",
    "## 차주 계획",
    "## 주요 일정 및 수치",
)


def render_summary(structured: StructuredReport) -> str:
    """Render every structured item without another lossy LLM summarization pass."""
    def display(item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            day = item.get("day")
            work = item.get("work") or item.get("schedule")
            if day and work:
                return f"{day}: {work}"
        return json.dumps(item, ensure_ascii=False, sort_keys=True)

    def section(title: str, items: list[Any]) -> str:
        if not items:
            return f"{title}\n\n- 없음"
        lines = [display(item) for item in items]
        return title + "\n\n" + "\n".join(f"- {line}" for line in lines)

    return "\n\n".join((
        section(SUMMARY_HEADINGS[0], structured.completed_work),
        section(SUMMARY_HEADINGS[1], structured.planned_work),
        section(SUMMARY_HEADINGS[2], structured.issues),
        section(SUMMARY_HEADINGS[3], structured.next_week_plan),
        section(SUMMARY_HEADINGS[4], structured.weekly_schedule),
    ))


class OllamaService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def _chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "think": False,
            "messages": messages,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            payload["format"] = "json"
        async with _llm_semaphore:
            owns_client = self._client is None
            client = self._client or httpx.AsyncClient(timeout=self.settings.ollama_timeout_seconds)
            try:
                response = await client.post(f"{self.settings.ollama_url}/api/chat", json=payload)
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError("Ollama 응답 시간이 제한을 초과했습니다.") from exc
            except httpx.ConnectError as exc:
                raise OllamaConnectionError("Ollama 서버에 연결할 수 없습니다.") from exc
            except httpx.HTTPError as exc:
                raise OllamaConnectionError("Ollama 통신 중 오류가 발생했습니다.") from exc
            finally:
                if owns_client:
                    await client.aclose()
        if response.status_code == 404:
            raise OllamaModelNotFoundError(
                f"Ollama 모델 '{self.settings.ollama_model}'이 설치되어 있지 않습니다."
            )
        if response.is_error:
            detail = response.text[:300]
            if "model" in detail.lower() and "not found" in detail.lower():
                raise OllamaModelNotFoundError(
                    f"Ollama 모델 '{self.settings.ollama_model}'이 설치되어 있지 않습니다."
                )
            raise OllamaResponseError(f"Ollama API 오류({response.status_code})")
        try:
            return response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaResponseError("Ollama 응답 형식이 올바르지 않습니다.") from exc

    async def _partial_summary(self, chunk: str, number: int, total: int) -> str:
        return await self._chat([
            {
                "role": "system",
                "content": "문서 조각에 명시된 업무, 일정, 수치, 문제점만 빠짐없이 간단히 정리하라. 추측하지 마라.",
            },
            {"role": "user", "content": f"조각 {number}/{total}\n\n{chunk}"},
        ])

    async def structure_document(
        self,
        text: str,
        *,
        report_date: str | None = None,
        department: str | None = None,
        author: str | None = None,
    ) -> StructuredReport:
        chunks = split_text(text, self.settings.text_chunk_size)
        source = text
        if len(chunks) > 1:
            partials = [
                await self._partial_summary(chunk, number, len(chunks))
                for number, chunk in enumerate(chunks, start=1)
            ]
            source = "\n\n".join(f"[부분 요약 {i}]\n{part}" for i, part in enumerate(partials, 1))
        hints = json.dumps(
            {"report_date": report_date, "department": department, "author": author},
            ensure_ascii=False,
        )
        messages = [
            {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
            {"role": "user", "content": f"사용자 입력 메타데이터(참고용): {hints}\n\n문서:\n{source}"},
        ]
        first = await self._chat(messages, json_mode=True)
        try:
            data = parse_json_response(first)
            structured = StructuredReport.model_validate(data)
        except (OllamaJsonError, ValidationError):
            repaired = await self._chat([
                {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "다음 응답의 내용은 바꾸지 말고 요구된 JSON 객체 형식으로만 한 번 수정하라:\n" + first,
                },
            ], json_mode=True)
            try:
                structured = StructuredReport.model_validate(parse_json_response(repaired))
            except (OllamaJsonError, ValidationError) as exc:
                raise OllamaJsonError("형식 수정 재시도 후에도 JSON 파싱에 실패했습니다.") from exc
        for field in ("planned_work", "completed_work", "weekly_schedule", "issues", "next_week_plan"):
            setattr(structured, field, _deduplicate(getattr(structured, field)))
        return structured

    async def summarize(self, structured: StructuredReport) -> str:
        return render_summary(structured)
