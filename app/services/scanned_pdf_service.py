from __future__ import annotations

from pathlib import Path


class ScannedPdfError(RuntimeError):
    pass


class ScannedPdfService:
    """Extension point for a separately deployed OCR service."""

    def extract(self, _path: Path) -> str:
        raise ScannedPdfError(
            "스캔 PDF로 판단되었습니다. 현재 MVP에는 별도 OCR 서비스가 연결되어 있지 않습니다."
        )
