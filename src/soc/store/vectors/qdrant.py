"""Qdrant implementation for the box 8 Ticket vector store."""

import math
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from qdrant_client import QdrantClient, models

from soc.config import Settings
from soc.contracts import validate_contract

from .base import VectorSearchHit

_TICKET_COLLECTION = "closed_tickets"
_TICKET_SOURCE_KIND = "ticket"
_SCROLL_PAGE_SIZE = 256


def _positive_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("search_limit_must_be_positive")


def _vector_values(vector: Sequence[float], dimensions: int) -> list[float]:
    if len(vector) != dimensions:
        raise ValueError("embedding_dimension_mismatch")
    values = list(vector)
    if any(
        isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value)
        for value in values
    ):
        raise ValueError("embedding_values_must_be_finite_numbers")
    return [float(value) for value in values]


class QdrantVectorStore:
    """Store C19 Ticket documents and retrieve them by exact keywords or cosine score."""

    def __init__(
        self,
        client: QdrantClient,
        *,
        collection: str,
        dimensions: int,
        owns_client: bool = False,
    ):
        if not collection:
            raise ValueError("qdrant_collection_required")
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
            raise ValueError("embedding_dimensions_must_be_positive")
        self._client = client
        self._collection = collection
        self._dimensions = dimensions
        self._owns_client = owns_client
        self._closed = False

    def ensure_collection(self) -> None:
        """Create the configured collection or verify its vector size and indexes."""
        self._ensure_open()
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            info = self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            if not isinstance(vectors, models.VectorParams) or vectors.size != self._dimensions:
                raise ValueError("qdrant_collection_dimension_mismatch")
            if vectors.distance != models.Distance.COSINE:
                raise ValueError("qdrant_collection_distance_mismatch")

        for field_name in ("collection", "source_kind", "keywords"):
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )

    def upsert(self, document: Mapping[str, Any], vector: Sequence[float]) -> None:
        """Validate and persist one C19 document as a deterministic Qdrant point."""
        self._ensure_open()
        validated = validate_contract("VectorDoc", dict(document)).model_dump(mode="json")
        if (
            validated["collection"] != _TICKET_COLLECTION
            or validated["source_kind"] != _TICKET_SOURCE_KIND
        ):
            raise ValueError("only_closed_ticket_vector_docs_are_supported")
        point_id = uuid.uuid5(uuid.NAMESPACE_URL, f"0-ticket-soc:{validated['doc_id']}")
        self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=str(point_id),
                    vector=_vector_values(vector, self._dimensions),
                    payload=validated,
                )
            ],
            wait=True,
        )

    def search_by_vector(self, vector: Sequence[float], *, limit: int) -> list[VectorSearchHit]:
        """Return the nearest finalized Ticket documents for one embedding."""
        self._ensure_open()
        _positive_limit(limit)
        result = self._client.query_points(
            collection_name=self._collection,
            query=_vector_values(vector, self._dimensions),
            query_filter=self._ticket_filter(),
            with_payload=["source_id", "keywords"],
            limit=limit,
        )
        return [
            VectorSearchHit(
                ticket_id=point.payload["source_id"],
                score=float(point.score),
            )
            for point in result.points
            if point.payload and isinstance(point.payload.get("source_id"), str)
        ]

    def search_by_keywords(self, keywords: Sequence[str], *, limit: int) -> list[VectorSearchHit]:
        """Return Ticket documents containing exact keyword values, ranked by overlap."""
        self._ensure_open()
        _positive_limit(limit)
        requested = tuple(dict.fromkeys(keyword for keyword in keywords if keyword))
        if not requested:
            return []

        query_filter = self._ticket_filter()
        query_filter.must.append(
            models.FieldCondition(
                key="keywords",
                match=models.MatchAny(any=list(requested)),
            )
        )
        offset = None
        scores: list[VectorSearchHit] = []
        while True:
            records, next_offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=query_filter,
                limit=_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=["source_id", "keywords"],
                with_vectors=False,
            )
            for record in records:
                payload = record.payload
                if not payload or not isinstance(payload.get("source_id"), str):
                    continue
                stored = payload.get("keywords", [])
                if not isinstance(stored, list):
                    continue
                matched = tuple(sorted(set(requested).intersection(stored)))
                if matched:
                    scores.append(
                        VectorSearchHit(
                            ticket_id=payload["source_id"],
                            score=float(len(matched)),
                            matched_keywords=matched,
                        )
                    )
            if next_offset is None:
                break
            offset = next_offset

        scores.sort(key=lambda hit: (-hit.score, hit.ticket_id))
        return scores[:limit]

    def close(self) -> None:
        if not self._closed and self._owns_client:
            self._client.close()
        self._closed = True

    def _ticket_filter(self) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="collection",
                    match=models.MatchValue(value=_TICKET_COLLECTION),
                ),
                models.FieldCondition(
                    key="source_kind",
                    match=models.MatchValue(value=_TICKET_SOURCE_KIND),
                ),
            ]
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("qdrant_vector_store_is_closed")


def create_qdrant_vector_store(settings: Settings) -> QdrantVectorStore:
    """Build the configured Qdrant adapter, registered as the default backend."""
    configured = settings.vector_store
    client = QdrantClient(url=configured.url, timeout=configured.timeout_seconds)
    store = QdrantVectorStore(
        client,
        collection=configured.collection,
        dimensions=settings.embedder.dimensions,
        owns_client=True,
    )
    try:
        store.ensure_collection()
    except Exception:
        store.close()
        raise
    return store
