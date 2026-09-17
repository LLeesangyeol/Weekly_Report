from __future__ import annotations

from datetime import date

import pytest

from app.models import ReportStatus
from app.repositories.report_repository import ReportRepository
from app.services.knowledge_search_service import NO_EVIDENCE_ANSWER, KnowledgeSearchService
from app.services.vector_store_service import VectorHit


class FakeOllama:
    async def answer_from_sources(self, question: str, context: str) -> str:
        assert "취약점" in question
        assert "CVE-2026-1000" in context
        return "취약점 1건을 확인했습니다. [문서 1]"


class UncitedOllama:
    async def answer_from_sources(self, question: str, context: str) -> str:
        return "문서에는 없지만 아마 취약점이 있었을 것입니다."


class UncitedSupportedOllama:
    async def answer_from_sources(self, question: str, context: str) -> str:
        assert "작성자: 김대리" in context
        return "연차 사용 일정이 확인됩니다."


class RefusalOllama:
    async def answer_from_sources(self, question: str, context: str) -> str:
        return "[근거 없음]"


class EmbeddingOnlyOllama:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]

    async def answer_from_sources(self, question: str, context: str) -> str:
        raise AssertionError("근거 점수가 낮으면 LLM 답변 생성을 호출하면 안 됩니다.")


class NoModelCallOllama:
    async def embed(self, _texts):
        raise AssertionError("정확한 DB 통계 질문은 임베딩을 호출하면 안 됩니다.")

    async def answer_from_sources(self, _question, _context):
        raise AssertionError("정확한 DB 통계 질문은 LLM을 호출하면 안 됩니다.")


class NoEmbeddingForKeywordOllama:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("명확한 키워드 검색 결과가 있으면 임베딩을 호출하면 안 됩니다.")

    async def answer_from_sources(self, question: str, context: str) -> str:
        return "취약점이 확인되었습니다. [문서 1]"


class LowScoreVectorStore:
    def __init__(self, report_id: int):
        self.report_id = report_id

    def search(self, vector: list[float], limit: int = 12) -> list[VectorHit]:
        return [VectorHit(1, self.report_id, "서버 정기 점검", 0.42, None, None)]


@pytest.mark.asyncio
async def test_knowledge_search_returns_grounded_sources(db, settings):
    report = ReportRepository(db).create(
        original_filename="보안점검.pdf",
        stored_filename="11111111-1111-1111-1111-111111111111.pdf",
        file_path=str(settings.upload_dir / "sample.pdf"),
        file_size=10,
        content_type="application/pdf",
        source_type="pdf",
        model_name="test-model",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "서버 점검 중 CVE-2026-1000 취약점이 발견되었습니다."
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer("취약점 나온 거 알려줘", 5)

    assert mode == "llm"
    assert "[문서 1]" in answer
    assert hits[0].report.id == report.id


@pytest.mark.asyncio
async def test_knowledge_search_returns_explicit_no_evidence(db):
    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer("없는 우주 피자 기록", 5)

    assert answer == NO_EVIDENCE_ANSWER
    assert hits == []
    assert mode == "no_results"


@pytest.mark.asyncio
async def test_low_semantic_score_does_not_reach_llm(db, settings):
    report = ReportRepository(db).create(
        original_filename="서버점검.pdf",
        stored_filename="22222222-2222-2222-2222-222222222222.pdf",
        file_path=str(settings.upload_dir / "server.pdf"),
        file_size=10,
        content_type="application/pdf",
        source_type="pdf",
        model_name="test-model",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "서버 정기 점검을 완료했습니다."
    db.commit()

    service = KnowledgeSearchService(
        db,
        EmbeddingOnlyOllama(),
        LowScoreVectorStore(report.id),
        min_semantic_score=0.68,
    )
    answer, hits, mode = await service.answer("고양이가 우주에서 피자를 먹은 기록", 5)

    assert answer == NO_EVIDENCE_ANSWER
    assert hits == []
    assert mode == "no_results"


@pytest.mark.asyncio
async def test_keyword_hit_skips_embedding_for_faster_precise_search(db, settings):
    report = ReportRepository(db).create(
        original_filename="보안점검.pdf",
        stored_filename="keyword-only.pdf",
        file_path=str(settings.upload_dir / "keyword-only.pdf"),
        file_size=10,
        content_type="application/pdf",
        source_type="pdf",
        model_name="test-model",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "CVE 취약점 점검 결과를 기록했습니다."
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(
        db, NoEmbeddingForKeywordOllama(), LowScoreVectorStore(report.id)
    ).answer("취약점 알려줘", 5)

    assert mode == "llm"
    assert "취약점" in answer
    assert [hit.report.id for hit in hits] == [report.id]


@pytest.mark.asyncio
async def test_uncited_llm_claim_is_rejected(db, settings):
    report = ReportRepository(db).create(
        original_filename="보안점검.pdf",
        stored_filename="33333333-3333-3333-3333-333333333333.pdf",
        file_path=str(settings.upload_dir / "security.pdf"),
        file_size=10,
        content_type="application/pdf",
        source_type="pdf",
        model_name="test-model",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "보안 취약점 점검을 수행했습니다."
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, UncitedOllama()).answer("취약점 알려줘", 5)

    assert "질문과 관련된 문서 1개" in answer
    assert "문서 내용" not in answer
    assert len(hits) == 1
    assert mode == "search_fallback"


@pytest.mark.asyncio
async def test_synonym_query_returns_source_when_document_uses_different_word(db, settings):
    report = ReportRepository(db).create(
        original_filename="근태현황.xlsx",
        stored_filename="66666666-6666-6666-6666-666666666666.xlsx",
        file_path=str(settings.upload_dir / "attendance.xlsx"),
        file_size=10,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        source_type="xlsx",
        model_name="test-model",
        author="김대리",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "김대리는 9월 3일 연차를 사용했습니다."
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, UncitedSupportedOllama()).answer("휴가 쓴 사람 알려줘", 5)

    assert mode == "search"
    assert hits[0].report.id == report.id
    assert "[문서 1]" in answer


@pytest.mark.asyncio
async def test_leave_person_question_uses_author_metadata_when_llm_refuses(db, settings):
    report = ReportRepository(db).create(
        original_filename="주간업무일지-주강수.pptx",
        stored_filename="77777777-7777-7777-7777-777777777777.pptx",
        file_path=str(settings.upload_dir / "leave-weekly.pptx"),
        file_size=10,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source_type="pptx",
        model_name="test-model",
        author="주강수",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "7월 30일과 31일에 연차 휴가를 사용했습니다."
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, RefusalOllama()).answer("휴가 쓴 사람 알려줘", 5)

    assert mode == "search"
    assert hits[0].report.id == report.id
    assert "주강수" in answer


@pytest.mark.asyncio
async def test_author_lookup_strips_korean_particle_and_returns_document_list(db, settings):
    report = ReportRepository(db).create(
        original_filename="주간업무일지-이상열.pptx",
        stored_filename="44444444-4444-4444-4444-444444444444.pptx",
        file_path=str(settings.upload_dir / "weekly.pptx"),
        file_size=10,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source_type="pptx",
        model_name="test-model",
        author="이상열",
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "주간 업무 일지"
    other = ReportRepository(db).create(
        original_filename="주간업무일지-김태형.pptx",
        stored_filename="55555555-5555-5555-5555-555555555555.pptx",
        file_path=str(settings.upload_dir / "other-weekly.pptx"),
        file_size=10,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source_type="pptx",
        model_name="test-model",
        author="김태형",
    )
    other.status = ReportStatus.COMPLETED.value
    other.extracted_text = "주간 업무 일지"
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer("이상열이 작성한 주간업무일지 찾아줘", 5)

    assert mode == "search"
    assert hits[0].report.id == report.id
    assert all(hit.report.author == "이상열" for hit in hits)
    assert "이상열" in answer


@pytest.mark.asyncio
async def test_date_question_returns_every_matching_report_without_llm(db, settings):
    repository = ReportRepository(db)
    for number, author in enumerate(("김대리", "이사원"), start=1):
        report = repository.create(
            original_filename=f"주간업무일지-{author}.pptx",
            stored_filename=f"date-{number}.pptx",
            file_path=str(settings.upload_dir / f"date-{number}.pptx"),
            file_size=10,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            source_type="pptx",
            model_name="test-model",
            author=author,
            report_date=date(2026, 8, 31),
        )
        report.status = ReportStatus.COMPLETED.value
        report.structured_json = {
            "completed_work": [{"day": "월(31)", "work": f"{author} 업무"}],
            "weekly_schedule": [{"day": "월(31)", "schedule": f"{author} 일정"}],
        }
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer(
        "8월 31일에 진행된 업무와 주요 일정은?", 5
    )

    assert mode == "date_summary"
    assert len(hits) == 2
    assert "김대리 업무" in answer
    assert "이사원 일정" in answer
    assert "[문서 1]" in answer and "[문서 2]" in answer


@pytest.mark.asyncio
async def test_day_only_question_returns_only_that_days_work_not_the_whole_week(db, settings):
    repository = ReportRepository(db)
    for number, day, work in ((1, "월(31)", "월요일 방화벽 점검"), (2, "화(01)", "화요일 NAC 교육")):
        report = repository.create(
            original_filename=f"주간업무일지-{number}.pptx", stored_filename=f"day-{number}.pptx",
            file_path=str(settings.upload_dir / f"day-{number}.pptx"), file_size=10,
            content_type="application/pptx", source_type="pptx", model_name="test-model",
            author=f"작성자{number}", report_date=date(2026, 8, 31),
        )
        report.status = ReportStatus.COMPLETED.value
        report.structured_json = {
            "completed_work": [{"day": day, "work": work}],
            "weekly_schedule": [{"day": day, "schedule": f"{work} 일정"}],
        }
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, NoModelCallOllama()).answer("31일 내용 알려줘", 30)

    assert mode == "date_summary"
    assert len(hits) == 1
    assert "월요일 방화벽 점검" in answer
    assert "화요일 NAC 교육" not in answer


@pytest.mark.asyncio
async def test_date_answer_explains_when_completed_work_has_no_day(db, settings):
    report = ReportRepository(db).create(
        original_filename="주간업무일지-날짜없음.pptx", stored_filename="undated-work.pptx",
        file_path=str(settings.upload_dir / "undated-work.pptx"), file_size=10,
        content_type="application/pptx", source_type="pptx", model_name="test-model",
        report_date=date(2026, 8, 31),
    )
    report.status = ReportStatus.COMPLETED.value
    report.structured_json = {
        "completed_work": [{"work": "금주 완료 업무"}],
        "weekly_schedule": [{"day": "월(31)", "schedule": "31일 주요 일정"}],
    }
    db.commit()

    answer, _, mode = await KnowledgeSearchService(db, NoModelCallOllama()).answer("8월 31일 업무 알려줘", 30)

    assert mode == "date_summary"
    assert "31일 주요 일정" in answer
    assert "완료 업무는 요일별로 기록되지 않아" in answer


@pytest.mark.asyncio
async def test_date_and_author_question_requires_both_exact_month_day_and_author(db, settings):
    repository = ReportRepository(db)
    cases = (
        ("이동훈", date(2026, 8, 3), "화(04)", "8월 이동훈 업무"),
        ("김태형", date(2026, 8, 3), "화(04)", "8월 다른 사람 업무"),
        ("이동훈", date(2026, 8, 31), "금(04)", "9월 이동훈 업무"),
    )
    for number, (author, report_date, day_label, work) in enumerate(cases, start=1):
        report = repository.create(
            original_filename=f"주간업무일지-{number}.pptx", stored_filename=f"exact-{number}.pptx",
            file_path=str(settings.upload_dir / f"exact-{number}.pptx"), file_size=10,
            content_type="application/pptx", source_type="pptx", model_name="test-model",
            author=author, report_date=report_date,
        )
        report.status = ReportStatus.COMPLETED.value
        report.structured_json = {
            "completed_work": [{"day": day_label, "work": work}],
            "weekly_schedule": [{"day": day_label, "schedule": f"{work} 일정"}],
        }
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, NoModelCallOllama()).answer(
        "8월 4일에 이동훈이 진행한 업무를 알려줘", 30
    )

    assert mode == "date_summary"
    assert len(hits) == 1
    assert hits[0].report.author == "이동훈"
    assert "8월 이동훈 업무" in answer
    assert "8월 다른 사람 업무" not in answer
    assert "9월 이동훈 업무" not in answer


@pytest.mark.asyncio
async def test_last_month_query_excludes_other_months(db, settings, monkeypatch):
    import app.services.knowledge_search_service as search_module

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)

    monkeypatch.setattr(search_module, "date", FixedDate)
    repository = ReportRepository(db)
    for number, report_date in enumerate((date(2026, 8, 3), date(2026, 7, 6)), start=1):
        report = repository.create(
            original_filename=f"다이텍-{number}.pptx",
            stored_filename=f"month-{number}.pptx",
            file_path=str(settings.upload_dir / f"month-{number}.pptx"),
            file_size=10,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            source_type="pptx",
            model_name="test-model",
            report_date=report_date,
        )
        report.status = ReportStatus.COMPLETED.value
        report.extracted_text = "다이텍연구원 방문 업무"
    db.commit()

    hits = KnowledgeSearchService(db, FakeOllama()).retrieve("지난달 다이텍 관련 업무를 요약해줘", 10)

    assert len(hits) == 1
    assert hits[0].report.report_date == date(2026, 8, 3)


@pytest.mark.asyncio
async def test_summary_query_only_returns_items_matching_the_requested_keyword(db, settings):
    repository = ReportRepository(db)
    for number, name, work in (
        (1, "다이텍", "다이텍연구원 방화벽 정기점검"),
        (2, "다른고객사", "경북대학교병원 NAC 점검"),
    ):
        report = repository.create(
            original_filename=f"{name}.pptx",
            stored_filename=f"strict-{number}.pptx",
            file_path=str(settings.upload_dir / f"strict-{number}.pptx"),
            file_size=10,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            source_type="pptx",
            model_name="test-model",
            author=name,
        )
        report.status = ReportStatus.COMPLETED.value
        report.structured_json = {"completed_work": [{"work": work}]}
        report.extracted_text = work
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer("다이텍 관련 업무를 요약해줘", 10)

    assert mode == "structured_summary"
    assert [hit.report.author for hit in hits] == ["다이텍"]
    assert "다이텍연구원 방화벽 정기점검" in answer
    assert "경북대학교병원" not in answer


@pytest.mark.asyncio
async def test_vulnerability_findings_query_excludes_weekly_tasks_that_only_mention_vulnerabilities(db, settings):
    repository = ReportRepository(db)
    finding = repository.create(
        original_filename="취약점 분석 결과보고서.hwp", stored_filename="finding.hwp",
        file_path=str(settings.upload_dir / "finding.hwp"), file_size=10,
        content_type="application/x-hwp", source_type="hwp", model_name="test-model",
        report_date=date(2026, 8, 31),
    )
    finding.status = ReportStatus.COMPLETED.value
    finding.extracted_text = "점검 내용 U-01 root 원격 접속 점검 결과 취약 조치 내용 root 로그인을 제한"
    finding.summary = "## 점검 개요\n- 확인된 점검 항목: 1건\n## 주요 조치 사항\n- U-01 root 원격 접속: root 로그인을 제한"
    weekly = repository.create(
        original_filename="주간업무일지.pptx", stored_filename="weekly-security.pptx",
        file_path=str(settings.upload_dir / "weekly-security.pptx"), file_size=10,
        content_type="application/pptx", source_type="pptx", model_name="test-model",
    )
    weekly.status = ReportStatus.COMPLETED.value
    weekly.extracted_text = "취약점 관련 NAC 패치 작업을 진행했다"
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, FakeOllama()).answer("지금까지 발견된 취약점을 날짜별로 정리해줘", 10)

    assert mode == "vulnerability_summary"
    assert [hit.report.id for hit in hits] == [finding.id]
    assert "root 로그인을 제한" in answer
    assert "NAC 패치" not in answer


@pytest.mark.asyncio
async def test_weekly_report_count_uses_all_active_database_rows_without_llm(db, settings):
    repository = ReportRepository(db)
    created = []
    for number in range(12):
        report = repository.create(
            original_filename=f"주간업무일지-{number}.pptx", stored_filename=f"count-{number}.pptx",
            file_path=str(settings.upload_dir / f"count-{number}.pptx"), file_size=10,
            content_type="application/pptx", source_type="pptx", model_name="test-model",
        )
        report.status = ReportStatus.COMPLETED.value
        created.append(report)
    repository.move_to_trash(created[-1])
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, NoModelCallOllama()).answer("현재 업무일지 몇 개 있냐?", 8)

    assert mode == "inventory"
    assert answer == "현재 휴지통을 제외한 업무일지는 총 11개입니다."
    assert hits == []


@pytest.mark.asyncio
async def test_direct_person_fact_question_is_answered_without_llm(db, settings):
    repository = ReportRepository(db)
    report = repository.create(
        original_filename="주간업무일지-김대리.pptx", stored_filename="direct-fact.pptx",
        file_path=str(settings.upload_dir / "direct-fact.pptx"), file_size=10,
        content_type="application/pptx", source_type="pptx", model_name="test-model",
        author="김대리", report_date=date(2026, 9, 14),
    )
    report.status = ReportStatus.COMPLETED.value
    report.extracted_text = "서버 정기 점검과 백업 복구 시험을 완료했다."
    report.structured_json = {"completed_work": [{"work": "서버 정기 점검과 백업 복구 시험 완료"}]}
    db.commit()

    answer, hits, mode = await KnowledgeSearchService(db, NoModelCallOllama()).answer(
        "서버 점검을 완료한 사람과 업무가 뭐야?", 30
    )

    assert mode == "direct_fact"
    assert [hit.report.id for hit in hits] == [report.id]
    assert "김대리" in answer
    assert "백업 복구 시험 완료" in answer
