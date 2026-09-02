from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.storage_service import StorageService, UploadValidationError, validate_extension


def make_upload(filename: str, body: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(body),
        headers=Headers({"content-type": content_type}),
    )


def test_allowed_extension_check():
    assert validate_extension("report.PPT") == ".ppt"
    assert validate_extension("report.pptx") == ".pptx"
    assert validate_extension("report.pdf") == ".pdf"
    with pytest.raises(UploadValidationError):
        validate_extension("report.exe")


@pytest.mark.asyncio
async def test_disguised_file_is_rejected(settings):
    upload = make_upload("fake.pdf", b"not really a pdf", "application/pdf")
    with pytest.raises(UploadValidationError, match="시그니처"):
        await StorageService(settings).save(upload)
    assert not list(settings.upload_dir.rglob("*.part"))


@pytest.mark.asyncio
async def test_file_size_limit(settings):
    upload = make_upload("large.pdf", b"%PDF-1.7\n" + b"x" * (1024 * 1024), "application/pdf")
    with pytest.raises(UploadValidationError, match="초과"):
        await StorageService(settings).save(upload)


@pytest.mark.asyncio
async def test_uuid_storage_filename(settings, pptx_bytes):
    upload = make_upload(
        "../unsafe name.pptx",
        pptx_bytes,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    stored = await StorageService(settings).save(upload)
    assert stored.original_filename == "unsafe name.pptx"
    assert stored.stored_filename.endswith(".pptx")
    assert len(stored.stored_filename) == 36 + 5
    assert stored.path.is_file()
    assert stored.path.parent.parent.parent == settings.upload_dir
