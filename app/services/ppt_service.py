from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.config import Settings


class PptExtractionError(RuntimeError):
    pass


def _shape_text(shape: Any) -> list[str]:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        lines: list[str] = []
        for child in sorted(shape.shapes, key=lambda item: (item.top, item.left)):
            lines.extend(_shape_text(child))
        return lines
    if getattr(shape, "has_table", False):
        rows: list[str] = []
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        return rows
    if getattr(shape, "has_text_frame", False):
        lines = []
        for paragraph in shape.text_frame.paragraphs:
            text = paragraph.text.strip()
            if text:
                lines.append(text)
        return lines
    return []


def extract_pptx_text(path: Path) -> str:
    try:
        presentation = Presentation(str(path))
    except Exception as exc:
        raise PptExtractionError("PPTX 문서를 열 수 없습니다.") from exc
    pages: list[str] = []
    for number, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        # Spatial ordering keeps top-to-bottom and, for equal rows, left-to-right layout.
        for shape in sorted(slide.shapes, key=lambda item: (item.top, item.left)):
            lines.extend(_shape_text(shape))
        pages.append(f"--- Slide {number} ---\n" + "\n".join(lines))
    return "\n\n".join(pages).strip()


class PptService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, path: Path) -> str:
        if path.suffix.lower() == ".pptx":
            return extract_pptx_text(path)
        if path.suffix.lower() != ".ppt":
            raise PptExtractionError("PPT 또는 PPTX 파일이 아닙니다.")
        return self._convert_and_extract(path)

    def _convert_and_extract(self, source: Path) -> str:
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="ppt-convert-", dir=self.settings.temp_dir))
        try:
            command = [
                self.settings.soffice_path,
                "--headless",
                "--convert-to",
                "pptx",
                "--outdir",
                str(work_dir),
                str(source),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.conversion_timeout_seconds,
                    check=False,
                    shell=False,
                )
            except FileNotFoundError as exc:
                raise PptExtractionError("LibreOffice(soffice)를 찾을 수 없습니다.") from exc
            except subprocess.TimeoutExpired as exc:
                raise PptExtractionError("PPT 변환 시간이 제한을 초과했습니다.") from exc
            converted = work_dir / f"{source.stem}.pptx"
            if result.returncode != 0 or not converted.is_file():
                detail = (result.stderr or result.stdout or "unknown error").strip()[-500:]
                raise PptExtractionError(f"PPT 변환에 실패했습니다: {detail}")
            return extract_pptx_text(converted)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
