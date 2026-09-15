from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.services.pdf_service import PdfService
from app.services.ppt_service import PptService
from app.services.kordoc_service import KordocService


class DocumentExtractionError(RuntimeError):
    pass


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        ppt_service: PptService | None = None,
        pdf_service: PdfService | None = None,
        kordoc_service: KordocService | None = None,
    ):
        self.ppt_service = ppt_service or PptService(settings)
        self.pdf_service = pdf_service or PdfService(settings)
        self.kordoc_service = kordoc_service or KordocService(settings.conversion_timeout_seconds)

    def extract(self, path: Path) -> str:
        extension = path.suffix.lower()
        if extension in {".ppt", ".pptx"}:
            text = self.ppt_service.extract(path)
        elif extension == ".pdf":
            text = self.pdf_service.extract(path)
        elif extension in {".hwp", ".hwpx", ".docx", ".xls", ".xlsx"}:
            text = self.kordoc_service.extract(path)
        else:
            raise DocumentExtractionError("지원하지 않는 문서 형식입니다.")
        if not text.strip():
            raise DocumentExtractionError("문서에서 텍스트를 추출하지 못했습니다.")
        return text
