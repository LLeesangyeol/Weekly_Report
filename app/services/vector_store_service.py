from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.models import DocumentChunk, Report


@dataclass(slots=True)
class VectorHit:
    chunk_id: int
    report_id: int
    content: str
    score: float
    page_number: int | None
    heading: str | None


class VectorStoreService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = QdrantClient(url=settings.qdrant_url) if settings.qdrant_url else QdrantClient(path=str(settings.qdrant_path))
        self.collection = settings.qdrant_collection

    def _ensure_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            configured = info.config.params.vectors
            existing_size = configured.size if hasattr(configured, "size") else None
            if existing_size and existing_size != vector_size:
                raise RuntimeError(
                    f"벡터 차원이 변경되었습니다({existing_size}→{vector_size}). 전체 재색인이 필요합니다."
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )
        if self.settings.qdrant_url:
            for field, schema in (
                ("report_id", models.PayloadSchemaType.INTEGER),
                ("report_date", models.PayloadSchemaType.KEYWORD),
                ("source_type", models.PayloadSchemaType.KEYWORD),
                ("department", models.PayloadSchemaType.KEYWORD),
            ):
                self.client.create_payload_index(self.collection, field, field_schema=schema)

    def index(self, report: Report, chunks: list[DocumentChunk], vectors: list[list[float]]) -> None:
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("청크와 임베딩 개수가 일치하지 않습니다.")
        self._ensure_collection(len(vectors[0]))
        self.delete_report(report.id)
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(models.PointStruct(
                id=chunk.id,
                vector=vector,
                payload={
                    "chunk_id": chunk.id,
                    "report_id": report.id,
                    "filename": report.original_filename,
                    "source_type": report.source_type,
                    "report_date": report.report_date.isoformat() if report.report_date else None,
                    "department": report.department,
                    "author": report.author,
                    "page_number": chunk.page_number,
                    "heading": chunk.heading,
                    "content": chunk.content,
                },
            ))
        self.client.upsert(collection_name=self.collection, points=points, wait=True)

    def delete_report(self, report_id: int) -> None:
        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[
                    models.FieldCondition(key="report_id", match=models.MatchValue(value=report_id))
                ])
            ),
            wait=True,
        )

    def search(self, vector: list[float], limit: int = 12) -> list[VectorHit]:
        if not self.client.collection_exists(self.collection):
            return []
        response = self.client.query_points(
            collection_name=self.collection, query=vector, limit=limit,
            with_payload=True, with_vectors=False,
        )
        hits: list[VectorHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(VectorHit(
                chunk_id=int(payload.get("chunk_id", point.id)),
                report_id=int(payload["report_id"]),
                content=str(payload.get("content", "")),
                score=float(point.score),
                page_number=payload.get("page_number"),
                heading=payload.get("heading"),
            ))
        return hits

    def status(self) -> dict[str, object]:
        exists = self.client.collection_exists(self.collection)
        points = self.client.count(self.collection).count if exists else 0
        return {"status": "ok", "collection": self.collection, "points": points, "mode": "server" if self.settings.qdrant_url else "embedded"}


@lru_cache(maxsize=4)
def get_vector_store(settings: Settings) -> VectorStoreService:
    return VectorStoreService(settings)
