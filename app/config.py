from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    upload_dir: Path
    temp_dir: Path
    ollama_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    max_upload_mb: int
    max_pdf_pages: int
    text_chunk_size: int
    disk_usage_limit_percent: float
    min_free_disk_gb: float
    soffice_path: str
    conversion_timeout_seconds: int

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    soffice = os.getenv("SOFFICE_PATH") or shutil.which("soffice") or "soffice"
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/weekly_report.db"),
        upload_dir=_project_path(os.getenv("UPLOAD_DIR", "./data/uploads")),
        temp_dir=_project_path(os.getenv("TEMP_DIR", "./data/temp")),
        ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "900")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "30")),
        max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "100")),
        text_chunk_size=int(os.getenv("TEXT_CHUNK_SIZE", "5000")),
        disk_usage_limit_percent=float(os.getenv("DISK_USAGE_LIMIT_PERCENT", "80")),
        min_free_disk_gb=float(os.getenv("MIN_FREE_DISK_GB", "15")),
        soffice_path=soffice,
        conversion_timeout_seconds=int(os.getenv("CONVERSION_TIMEOUT_SECONDS", "120")),
    )
