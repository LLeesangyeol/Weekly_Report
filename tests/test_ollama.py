from __future__ import annotations

import json

import httpx
import pytest

from app.services.ollama_service import OllamaService, parse_json_response


STRUCTURED = {
    "report_date": "2026-08-31",
    "department": "기술부",
    "author": "이상열",
    "planned_work": ["배포 준비"],
    "completed_work": ["테스트 완료"],
    "weekly_schedule": [],
    "issues": [],
    "next_week_plan": [],
}


def test_parse_plain_json():
    assert parse_json_response(json.dumps(STRUCTURED))["department"] == "기술부"


def test_parse_fenced_json():
    content = "```json\n" + json.dumps(STRUCTURED, ensure_ascii=False) + "\n```"
    assert parse_json_response(content)["author"] == "이상열"


@pytest.mark.asyncio
async def test_ollama_api_mock(settings):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["stream"] is False
        assert payload["model"] == "test-model"
        assert payload["options"]["temperature"] == 0.1
        assert payload["think"] is False
        assert payload["format"] == "json"
        content = json.dumps(STRUCTURED, ensure_ascii=False)
        return httpx.Response(200, json={"message": {"content": content}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = OllamaService(settings, client=client)
        structured = await service.structure_document("주간업무 실적사항: 테스트 완료")
        summary = await service.summarize(structured)
    assert structured.completed_work == ["테스트 완료"]
    assert summary.startswith("## 금주 완료 업무")
    assert "## 주요 일정" in summary
    assert "차주 계획" not in summary
    assert "월(31):" not in summary  # no schedule exists in this fixture
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_json_format_is_retried_once(settings):
    count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        content = "invalid" if count == 1 else json.dumps(STRUCTURED, ensure_ascii=False)
        return httpx.Response(200, json={"message": {"content": content}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OllamaService(settings, client=client).structure_document("문서")
    assert result.author == "이상열"
    assert count == 2
