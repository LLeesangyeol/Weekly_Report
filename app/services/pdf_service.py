from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.config import Settings
from app.services.scanned_pdf_service import ScannedPdfService


class PdfExtractionError(RuntimeError):
    pass


class PdfService:
    def __init__(self, settings: Settings, scanner: ScannedPdfService | None = None):
        self.settings = settings
        self.scanner = scanner or ScannedPdfService()

    def extract(self, path: Path) -> str:
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise PdfExtractionError("PDF 문서를 열 수 없습니다.") from exc
        if len(reader.pages) > self.settings.max_pdf_pages:
            raise PdfExtractionError(
                f"PDF 페이지 수가 제한({self.settings.max_pdf_pages}페이지)을 초과했습니다."
            )
        pages: list[str] = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise PdfExtractionError(f"PDF {number}페이지 텍스트 추출에 실패했습니다.") from exc
            pages.append(f"--- Page {number} ---\n{text.strip()}")
        extracted = "\n\n".join(pages).strip()
        visible_chars = sum(1 for char in extracted if char.isalnum())
        if visible_chars < max(20, len(reader.pages) * 5):
            return self.scanner.extract(path)
        return extracted
