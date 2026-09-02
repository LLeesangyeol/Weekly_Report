from app.services.weekly_template_service import parse_weekly_report_template


SAMPLE = """--- Slide 1 ---
2026년 08월 31일
부    서: 기술부
성    명: 이상열
[금주 예정 업무]
[예정 업무 영역 1]
[사내업무]
▪ Chapter 4 동영상 시청
  - 로그 및 리포트 정리
▪ Chapter 5 동영상 시청
[주간 일정 계획표]
- 월(31): 사내업무
- 화(01): 사내업무
[금주 업무 실적]
[실적 업무 영역 1]
▪ Chapter 1 동영상 시청
  - 노션 정리
[실적 업무 영역 2]
▪ NAS 설정
  - 사용자 생성
"""


def test_parse_approved_weekly_report_template_without_llm_guessing():
    parsed = parse_weekly_report_template(SAMPLE)
    assert parsed is not None
    assert parsed.department == "기술부"
    assert parsed.author == "이상열"
    assert parsed.planned_work == ["Chapter 4 동영상 시청\n- 로그 및 리포트 정리", "Chapter 5 동영상 시청"]
    assert parsed.completed_work == ["Chapter 1 동영상 시청\n- 노션 정리", "NAS 설정\n- 사용자 생성"]
    assert parsed.weekly_schedule == [{"day": "월(31)", "work": "사내업무"}, {"day": "화(01)", "work": "사내업무"}]
    assert parsed.issues == []
    assert parsed.next_week_plan == []


def test_parse_template_keeps_unbulleted_work_blocks():
    plain = SAMPLE.replace("▪ Chapter 4 동영상 시청", "고객사 A 방문\n- 정기점검").replace("▪ Chapter 1 동영상 시청", "고객사 B 방문\n- 장애 조치")
    parsed = parse_weekly_report_template(plain)
    assert parsed.planned_work[0] == "고객사 A 방문\n- 정기점검\n- 로그 및 리포트 정리"
    assert parsed.completed_work[0] == "고객사 B 방문\n- 장애 조치\n- 노션 정리"
