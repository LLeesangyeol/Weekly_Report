from pathlib import Path
from types import SimpleNamespace

from app.services.ppt_service import PptService, extract_pptx_text


def test_pptx_extracts_text_boxes_tables_and_order(tmp_path: Path, pptx_bytes: bytes):
    path = tmp_path / "report.pptx"
    path.write_bytes(pptx_bytes)
    text = extract_pptx_text(path)
    assert "--- Slide 1 ---" in text
    assert "금주 예정 업무" in text
    assert "주간업무 실적사항" in text
    assert "요일 | 계획" in text
    assert "월 | 정기회의" in text
    assert text.index("금주 예정 업무") < text.index("주간업무 실적사항")


def test_legacy_ppt_conversion_flow_and_temp_cleanup(
    tmp_path: Path, settings, pptx_bytes: bytes, monkeypatch
):
    source = tmp_path / "legacy.ppt"
    source.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"placeholder")

    def fake_run(command, **kwargs):
        assert command[0] == settings.soffice_path
        assert "--headless" in command
        assert kwargs["timeout"] == settings.conversion_timeout_seconds
        output_dir = Path(command[command.index("--outdir") + 1])
        (output_dir / "legacy.pptx").write_bytes(pptx_bytes)
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("app.services.ppt_service.subprocess.run", fake_run)
    text = PptService(settings).extract(source)
    assert "정기회의" in text
    assert list(settings.temp_dir.iterdir()) == []
