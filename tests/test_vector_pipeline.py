from __future__ import annotations

from dataclasses import replace

from app.repositories.report_repository import ReportRepository
from app.services.chunking_service import chunk_document
from app.services.vector_store_service import VectorStoreService


def test_chunk_document_preserves_page_and_heading():
    chunks = chunk_document("--- Page 2 ---\n## 보안 점검\nCVE 취약점이 발견되었습니다.", size=200, overlap=20)
    assert len(chunks) == 1
    assert chunks[0].page_number == 2
    assert chunks[0].heading == "보안 점검"


def test_embedded_qdrant_indexes_and_searches(db, settings, tmp_path):
    repository = ReportRepository(db)
    report = repository.create(
        original_filename="security.pdf", stored_filename="vector-test.pdf",
        file_path=str(tmp_path / "security.pdf"), file_size=10,
        content_type="application/pdf", source_type="pdf", model_name="test",
    )
    chunks = repository.replace_chunks(report, [{
        "ordinal": 0, "page_number": 3, "heading": "취약점",
        "content": "서버 취약점 점검 결과", "token_estimate": 5,
    }])
    local_settings = replace(settings, qdrant_path=tmp_path / "vectors", qdrant_collection="test_chunks")
    store = VectorStoreService(local_settings)
    try:
        store.index(report, chunks, [[1.0, 0.0, 0.0]])
        hits = store.search([1.0, 0.0, 0.0], limit=1)
        assert hits[0].report_id == report.id
        assert hits[0].page_number == 3
        assert store.status()["points"] == 1
    finally:
        store.client.close()
