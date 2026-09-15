from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class KordocError(RuntimeError):
    pass


def _find_node() -> str:
    configured = os.getenv("NODE_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    discovered = shutil.which("node") or shutil.which("node.exe")
    if discovered:
        return discovered
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if bundled.is_file():
        return str(bundled)
    return "node"


class KordocService:
    def __init__(self, timeout_seconds: int = 180):
        self.node = _find_node()
        self.script = Path(__file__).resolve().parents[2] / "parser" / "parse.mjs"
        self.timeout_seconds = timeout_seconds

    def extract(self, path: Path) -> str:
        if not self.script.is_file():
            raise KordocError("Kordoc 파서가 설치되어 있지 않습니다.")
        try:
            result = subprocess.run(
                [self.node, str(self.script), str(path.resolve())],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", timeout=self.timeout_seconds,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise KordocError("Node.js를 찾을 수 없습니다. NODE_EXECUTABLE 경로를 확인하세요.") from exc
        except subprocess.TimeoutExpired as exc:
            raise KordocError("Kordoc 문서 분석 시간이 제한을 초과했습니다.") from exc
        if result.returncode != 0:
            raise KordocError((result.stderr or "Kordoc 문서 분석에 실패했습니다.")[:1000])
        if not result.stdout.strip():
            raise KordocError("문서에서 텍스트를 추출하지 못했습니다.")
        return result.stdout
