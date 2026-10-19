"""Branch result store interface (box 25, C21, D-002, docs/extensibility.md).

Box 25 records where each alert (later: ticket) went. A subject is branched
once: a second C21 for the same ``(subject_type, subject_id)`` is refused, so
"a C21 exists" means "this subject is done". ``seq`` grows in the order results
were saved; L1 entity lookup (2-6) reads ``l1_entity_lookup`` results by it.

Implementations are registered in the ``stores`` registry as
``<backend>.branches`` (and ``<backend>.readonly_branches`` for the read-only
account) and opened with ``soc.store.open_store("branches", ...)``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from soc.config import Settings
from soc.contracts import BranchResult
from soc.store.paging import literal_values

STORE_KIND = "branches"
READONLY_STORE_KIND = "readonly_branches"

SUBJECT_TYPES = literal_values(BranchResult, "subject_type")
PATHS = literal_values(BranchResult, "path")


class DuplicateBranchError(ValueError):
    """This subject, or this branch_id, already has a C21."""


@dataclass(frozen=True)
class StoredBranch:
    """A C21 with its storage position. ``seq`` grows in save order."""

    seq: int
    record: BranchResult


class BranchStore(Protocol):
    def save(self, record: BranchResult) -> StoredBranch:
        """Store a C21. Raises DuplicateBranchError if its subject or ID is already stored."""
        ...

    def get(self, subject_type: str, subject_id: str) -> BranchResult | None:
        """The C21 of this subject; None if it has not been branched."""
        ...

    def list_by_path(
        self, path: str, after_seq: int | None, limit: int
    ) -> tuple[StoredBranch, ...]:
        """At most ``limit`` (>= 1) C21 of ``path`` after ``after_seq``, oldest first."""
        ...

    def close(self) -> None: ...


class BranchStoreFactory(Protocol):
    """What a backend registers as ``<backend>.branches`` in the ``stores`` registry."""

    def __call__(self, settings: Settings, environ: Mapping[str, str]) -> BranchStore: ...
