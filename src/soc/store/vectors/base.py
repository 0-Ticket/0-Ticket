"""Vector store boundary for the unnumbered Vector DB (C19)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    """One Ticket returned by exact-keyword or vector retrieval."""

    ticket_id: str
    score: float
    matched_keywords: tuple[str, ...] = ()


class VectorStore(Protocol):
    """Operations needed by the Ticket vector service, independent of backend."""

    def upsert(self, document: Mapping[str, Any], vector: Sequence[float]) -> None: ...

    def search_by_vector(
        self, vector: Sequence[float], *, limit: int
    ) -> Sequence[VectorSearchHit]: ...

    def search_by_keywords(
        self, keywords: Sequence[str], *, limit: int
    ) -> Sequence[VectorSearchHit]: ...

    def close(self) -> None: ...
