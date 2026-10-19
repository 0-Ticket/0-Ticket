"""Alert and Event store interface (boxes 6, 7, D-002, docs/extensibility.md).

Source records are the C2 SiemAlert items the core SIEM entry produced, stored
as they arrived and never changed (K8, K9). Normalized results (C5 AlertRecord,
C13 EventRecord) live apart and point at their source row by
``source_record_id`` (K67). Later boxes may update C5 and C13; the source never.
Normalization (box 4) saves its results, its C12 failures and how far it has
read in one batch, so a source record gets exactly one outcome.

Implementations are registered in the ``stores`` registry as
``<backend>.records`` and opened with ``soc.store.open_store("records", ...)``.
Changing this interface breaks plugins, so it follows the contract change
procedure (docs/data-contracts.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from soc.config import Settings
from soc.contracts import AlertRecord, EventRecord, NormalizeFailure, SiemAlert

STORE_KIND = "records"

SourceKind = Literal["alert", "event"]

# Normalized fields a record can be looked up by, each with time (the indexed pairs).
EntityField = Literal["src_ip", "dst_ip", "host"]
ENTITY_FIELDS: tuple[EntityField, ...] = ("src_ip", "dst_ip", "host")


class UnknownSourceError(LookupError):
    """A normalized record names a source record that is not stored, or is of the other kind."""


class DuplicateRecordError(ValueError):
    """A normalized record with this ID, or another outcome for its source, is already stored."""


@dataclass(frozen=True)
class SaveResult:
    """How many source records a save added, and how many were already stored."""

    inserted: int
    duplicates: int


@dataclass(frozen=True)
class StoredSource:
    """A source record with its storage position. ``seq`` grows in arrival order."""

    seq: int
    ingested_at: int
    record: SiemAlert


@dataclass(frozen=True)
class SourceFailure:
    """A C12 and the source record it is about. C12 itself does not carry the ID."""

    source_record_id: str
    failure: NormalizeFailure


@dataclass(frozen=True)
class PurgeResult:
    """Expired source records deleted, and expired ones kept because a result points at them."""

    deleted: int
    skipped: int


class RecordStore(Protocol):
    def save_source_records(
        self, items: Sequence[SiemAlert], cursor_key: str, next_cursor: str | None
    ) -> SaveResult:
        """Store new C2 items and the cursor after them, together or not at all.

        An item whose source_record_id is already stored is counted as a
        duplicate and left as it is. Each item must be valid C2 whose ID is the
        hash of its content.
        """
        ...

    def load_cursor(self, cursor_key: str) -> str | None:
        """The cursor last saved under ``cursor_key``; None if there is none."""
        ...

    def get_source_record(self, source_record_id: str) -> SiemAlert | None: ...

    def list_source_records(
        self, kind: Literal["alert", "event"], after_seq: int | None, limit: int
    ) -> tuple[StoredSource, ...]:
        """At most ``limit`` (>= 1) source records of ``kind`` after ``after_seq``, oldest first.

        This is how normalization (box 4) reads its input.
        """
        ...

    def save_alert_record(self, record: AlertRecord) -> None:
        """Store a C5. Raises UnknownSourceError or DuplicateRecordError."""
        ...

    def save_event_record(self, record: EventRecord) -> None:
        """Store a C13. Raises UnknownSourceError or DuplicateRecordError."""
        ...

    def get_alert_record(self, alert_id: str) -> AlertRecord | None: ...

    def get_event_record(self, event_id: str) -> EventRecord | None: ...

    def find_alert_records(
        self, field: EntityField, value: str, time_from: int, time_to: int, limit: int
    ) -> tuple[AlertRecord, ...]:
        """C5 whose ``field`` equals ``value`` and ``time_from <= time < time_to``, by time."""
        ...

    def find_event_records(
        self, field: EntityField, value: str, time_from: int, time_to: int, limit: int
    ) -> tuple[EventRecord, ...]:
        """C13 whose ``field`` equals ``value`` and ``time_from <= time < time_to``, by time."""
        ...

    def load_normalize_position(self, kind: SourceKind) -> int | None:
        """The ``seq`` of the last source record of ``kind`` normalized; None before the first."""
        ...

    def save_normalize_batch(
        self,
        kind: SourceKind,
        records: Sequence[AlertRecord] | Sequence[EventRecord],
        failures: Sequence[SourceFailure],
        last_seq: int,
    ) -> None:
        """Store one normalization batch of ``kind`` and move its position to ``last_seq``.

        All or nothing. ``records`` are C5 for ``alert`` and C13 for ``event``;
        every record and failure must point at a stored source of ``kind``
        (UnknownSourceError) that has no outcome yet (DuplicateRecordError).
        The position never moves back (ValueError).
        """
        ...

    def get_normalize_failure(self, source_record_id: str) -> NormalizeFailure | None: ...

    def purge_expired(self, now: int) -> PurgeResult:
        """Delete source records stored longer than the retention setting before ``now``.

        A source a normalized result or a C12 failure still points at is kept and counted as
        skipped. With retention 0 (forever) nothing is deleted.
        """
        ...

    def close(self) -> None: ...


class RecordStoreFactory(Protocol):
    """What a backend registers as ``<backend>.records`` in the ``stores`` registry.

    Retention comes from ``settings.store.raw_retention_days``; secrets are read
    from ``environ`` through ``soc.config.read_secret``.
    """

    def __call__(self, settings: Settings, environ: Mapping[str, str]) -> RecordStore: ...
