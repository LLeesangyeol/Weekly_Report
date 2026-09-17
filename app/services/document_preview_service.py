from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings


class PreviewError(RuntimeError):
    pass


class DocumentPreviewService:
    """Preserve document visuals by creating a PDF preview beside uploaded files."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.preview_dir = settings.upload_dir / "previews"

    def create(self, source: Path, report_id: int) -> Path:
        if source.suffix.lower() == ".pdf":
            return source
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        destination = self.preview_dir / f"{report_id}.pdf"
        with tempfile.TemporaryDirectory(dir=self.settings.temp_dir, prefix="preview-") as temporary:
            work_dir = Path(temporary)
            profile = work_dir / "lo-profile"
            profile.mkdir()
            command = [
                self.settings.soffice_path,
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(source),
            ]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=self.settings.conversion_timeout_seconds, shell=False)
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                raise PreviewError("문서 미리보기를 만들 수 없습니다.") from exc
            converted = work_dir / f"{source.stem}.pdf"
            if result.returncode != 0 or not converted.is_file():
                raise PreviewError("문서 미리보기를 만들 수 없습니다.")
            shutil.copy2(converted, destination)
        return destination
