from app.services.document_summary_service import summarize_heading_document, summarize_structured_document


def test_heading_document_summary_separates_actions_and_logs():
    text = """
#### 1. DNS 제어
DNS 서버 주소는 설정값으로 변경됨. 로그: `[DNS 서버 주소 변경]`
#### 2. Windows 보안 설정 시간 동기화
서버 날짜 및 시간 설정 시 동기화 확인. 로그: `[시간 동기화 상태 확인]`
#### 3. 로그 확인 예시
로그: `[DNS 서버 주소 변경]`
"""
    summary = summarize_heading_document(text)

    assert summary is not None
    assert "## 문서 핵심 항목" in summary
    assert "DNS 제어: DNS 서버 주소는 설정값으로 변경됨." in summary
    assert "Windows 보안 설정 시간 동기화" in summary
    assert "## 확인 로그" in summary
    assert summary.count("[DNS 서버 주소 변경]") == 1


def test_generic_structural_summary_handles_unrelated_bullet_documents():
    summary = summarize_structured_document("""
- 서버 교체 일정을 9월 20일로 확정
- 백업 복구 시험을 완료
- 운영 전 방화벽 정책 검토 필요
""")

    assert summary == "## 핵심 항목\n- 서버 교체 일정을 9월 20일로 확정\n- 백업 복구 시험을 완료\n- 운영 전 방화벽 정책 검토 필요"
