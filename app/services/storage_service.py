from __future__ import annotations

import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings


ALLOWED_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
EXPECTED_MIME_TYPES = {
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip"},
    ".pdf": {"application/pdf"},
}


class UploadValidationError(ValueError):
    pass


class InsufficientStorageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredUpload:
    original_filename: str
    stored_filename: str
    path: Path
    size: int
    content_type: str
    source_type: str


def validate_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("지원하지 않는 파일 형식입니다. PPT, PPTX, PDF만 업로드할 수 있습니다.")
    return extension


def _validate_signature(path: Path, extension: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(8)
    if extension == ".pdf" and not header.startswith(b"%PDF-"):
        raise UploadValidationError("PDF 파일 시그니처가 올바르지 않습니다.")
    if extension == ".ppt" and header != bytes.fromhex("D0CF11E0A1B11AE1"):
        raise UploadValidationError("PPT 파일 시그니처가 올바르지 않습니다.")
    if extension == ".pptx":
        if not header.startswith(b"PK"):
            raise UploadValidationError("PPTX 파일 시그니처가 올바르지 않습니다.")
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                    raise UploadValidationError("유효한 PPTX 패키지가 아닙니다.")
        except zipfile.BadZipFile as exc:
            raise UploadValidationError("손상된 PPTX 파일입니다.") from exc


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _ensure_capacity(self) -> None:
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.settings.upload_dir)
        used_percent = (usage.used / usage.total * 100) if usage.total else 100
        free_gb = usage.free / (1024**3)
        if used_percent >= self.settings.disk_usage_limit_percent or free_gb < self.settings.min_free_disk_gb:
            raise InsufficientStorageError("서버 저장 공간이 부족하여 신규 업로드가 차단되었습니다.")

    async def save(self, upload: UploadFile) -> StoredUpload:
        original = Path(upload.filename or "").name
        if not original:
            raise UploadValidationError("파일명이 없습니다.")
        extension = validate_extension(original)
        content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
        if content_type not in GENERIC_MIME_TYPES and content_type not in EXPECTED_MIME_TYPES[extension]:
            raise UploadValidationError("파일 확장자와 MIME 유형이 일치하지 않습니다.")

        self._ensure_capacity()
        now = datetime.now()
        destination_dir = self.settings.upload_dir / f"{now:%Y}" / f"{now:%m}"
        destination_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid.uuid4()}{extension}"
        destination = destination_dir / stored_filename
        partial = destination.with_suffix(destination.suffix + ".part")
        size = 0
        try:
            with partial.open("xb") as stream:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise UploadValidationError(
                            f"파일 크기는 {self.settings.max_upload_mb}MB를 초과할 수 없습니다."
                        )
                    stream.write(chunk)
            if size == 0:
                raise UploadValidationError("빈 파일은 업로드할 수 없습니다.")
            _validate_signature(partial, extension)
            partial.replace(destination)
        except Exception:
            partial.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return StoredUpload(
            original_filename=original,
            stored_filename=stored_filename,
            path=destination.resolve(),
            size=size,
            content_type=content_type or "application/octet-stream",
            source_type=extension.lstrip("."),
        )

    def safe_download_path(self, registered_path: str) -> Path:
        root = self.settings.upload_dir.resolve()
        path = Path(registered_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PermissionError("등록된 업로드 디렉터리 밖의 파일에는 접근할 수 없습니다.") from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
