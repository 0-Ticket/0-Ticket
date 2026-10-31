"""Vector store boundary for box 8 (C19)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


def _safe_exception_type_identifier(error: BaseException) -> str:
    """Return a short type identifier without consulting exception text."""
    name = type(error).__name__
    if name.isascii() and name.isidentifier() and len(name) <= 80:
        return name
    return "Exception"


class VectorStoreUnavailableError(RuntimeError):
    """A vector backend could not complete an operation due to a transient failure."""

    def __init__(self, dependency_error: BaseException):
        super().__init__("vector_store_unavailable")
        self.dependency_error_type = _safe_exception_type_identifier(dependency_error)


class VectorStoreInitializationCleanupError(RuntimeError):
    """Initialization failed and cleanup of the acquired vector resource also failed."""

    def __init__(self, initialization_error: BaseException, cleanup_error: BaseException):
        super().__init__("vector_store_initialization_cleanup_failed")
        self.initialization_error_type = _safe_exception_type_identifier(initialization_error)
        self.cleanup_error_type = _safe_exception_type_identifier(cleanup_error)


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
