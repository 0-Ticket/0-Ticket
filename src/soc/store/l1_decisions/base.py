"""L1 decision record store interface (boxes 11, 27, C23, D-002, docs/extensibility.md).

Box 11 (2-6, 2-7) records each promotion, hold and Ticket verdict; box 27
(3-5) only reads them. A subject may get more than one record over time (an
alert is held, a ticket is later decided), so ``get`` returns the latest.
Lists are newest first: ``created_at`` descending, then save order descending.

Implementations are registered in the ``stores`` registry as
``<backend>.l1_decisions`` (and ``<backend>.readonly_l1_decisions`` for the
read-only account) and opened with ``soc.store.open_store("l1_decisions", ...)``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from soc.config import Settings
from soc.contracts import L1DecisionRecord
from soc.store.paging import DEFAULT_PAGE_LIMIT, literal_values

STORE_KIND = "l1_decisions"
READONLY_STORE_KIND = "readonly_l1_decisions"

SUBJECT_TYPES = literal_values(L1DecisionRecord, "subject_type")
DECISIONS = literal_values(L1DecisionRecord, "decision")
REASONS = literal_values(L1DecisionRecord, "reason")


class DuplicateDecisionError(ValueError):
    """A C23 with this decision_id is already stored."""


@dataclass(frozen=True)
class DecisionPage:
    """One page of C23, newest first. ``next_cursor`` is None on the last page."""

    items: tuple[L1DecisionRecord, ...]
    next_cursor: str | None


class L1DecisionStore(Protocol):
    def save(self, record: L1DecisionRecord) -> L1DecisionRecord:
        """Store a C23. Raises DuplicateDecisionError if its decision_id is stored."""
        ...

    def get(self, subject_type: str, subject_id: str) -> L1DecisionRecord | None:
        """The latest C23 of this subject; None if there is none."""
        ...

    def list(
        self,
        *,
        subject_type: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> DecisionPage:
        """C23 matching every given filter, newest first, ``limit`` (1-200) per page.

        A filter value outside the C23 enum, or a cursor this method did not
        make, is a ValueError.
        """
        ...

    def close(self) -> None: ...


class L1DecisionStoreFactory(Protocol):
    """What a backend registers as ``<backend>.l1_decisions`` in the ``stores`` registry."""

    def __call__(self, settings: Settings, environ: Mapping[str, str]) -> L1DecisionStore: ...
