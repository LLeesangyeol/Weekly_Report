from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    ordinal: int
    content: str
    page_number: int | None = None
    heading: str | None = None


PAGE_MARKER = re.compile(r"^---\s*(?:Slide|Page)\s+(\d+)\s*---$", re.IGNORECASE)
HEADING = re.compile(r"^#{1,6}\s+(.+)$")


def chunk_document(text: str, size: int = 1200, overlap: int = 180) -> list[TextChunk]:
    if size < 200 or overlap < 0 or overlap >= size:
        raise ValueError("청크 크기와 중첩 범위가 올바르지 않습니다.")
    blocks: list[tuple[str, int | None, str | None]] = []
    page: int | None = None
    heading: str | None = None
    current: list[str] = []

    def flush() -> None:
        if current:
            value = "\n".join(current).strip()
            if value:
                blocks.append((value, page, heading))
            current.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        page_match = PAGE_MARKER.match(line)
        heading_match = HEADING.match(line)
        if page_match:
            flush()
            page = int(page_match.group(1))
            continue
        if heading_match:
            flush()
            heading = heading_match.group(1).strip()
            current.append(line)
            continue
        if not line:
            flush()
        else:
            current.append(raw_line.strip())
    flush()

    result: list[TextChunk] = []
    for block, block_page, block_heading in blocks:
        start = 0
        while start < len(block):
            end = min(len(block), start + size)
            if end < len(block):
                boundary = max(block.rfind("\n", start, end), block.rfind(". ", start, end))
                if boundary > start + size // 2:
                    end = boundary + 1
            value = block[start:end].strip()
            if value:
                prefix = f"{block_heading}\n" if block_heading and block_heading not in value[:100] else ""
                result.append(TextChunk(len(result), (prefix + value).strip(), block_page, block_heading))
            if end >= len(block):
                break
            start = max(start + 1, end - overlap)
    return result
