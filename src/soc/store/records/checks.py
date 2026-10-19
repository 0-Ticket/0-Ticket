"""Input checks every Alert/Event store applies before writing (boxes 6, 7).

Shared so a backend cannot drift from the rules: each item is checked with
``validate_contract`` and a source record's ID must be the hash of its content,
which is what makes the source row immutable and the save idempotent.
"""

from collections.abc import Sequence

from soc.contracts import (
    AlertRecord,
    ContractValidationError,
    EventRecord,
    SiemAlert,
    validate_contract,
)
from soc.ingest.connector import source_record_id

from .base import ENTITY_FIELDS, DuplicateRecordError, SourceFailure

DAY_MS = 86_400_000


def check_source_records(items: Sequence[SiemAlert]) -> tuple[SiemAlert, ...]:
    """Validate every item as C2 before any is written, so a bad item fails the whole batch."""
    checked = []
    for item in items:
        content = item.model_dump(mode="json")
        model = validate_contract("SiemAlert", content)
        if model.source_record_id != source_record_id(content):
            raise ContractValidationError("/source_record_id", "content_hash")
        checked.append(model)
    return tuple(checked)


def check_alert_record(record: AlertRecord) -> AlertRecord:
    return validate_contract("AlertRecord", record.model_dump(mode="json"))


def check_event_record(record: EventRecord) -> EventRecord:
    return validate_contract("EventRecord", record.model_dump(mode="json"))


def check_normalize_batch(
    kind: str,
    records: Sequence[AlertRecord] | Sequence[EventRecord],
    failures: Sequence[SourceFailure],
) -> tuple[tuple[AlertRecord | EventRecord, ...], tuple[SourceFailure, ...]]:
    """Validate a whole normalization batch before any of it is written.

    Each record must be the contract of ``kind`` (C5 for alert, C13 for event)
    and no two items may claim the same source record.
    """
    checks = {"alert": check_alert_record, "event": check_event_record}
    if kind not in checks:
        raise ValueError("kind must be alert or event")
    expected = AlertRecord if kind == "alert" else EventRecord
    checked_records = []
    for record in records:
        if not isinstance(record, expected):
            raise ValueError(f"{kind} batch: records must be {expected.__name__} (kind mismatch)")
        checked_records.append(checks[kind](record))
    checked_failures = tuple(
        SourceFailure(
            item.source_record_id,
            validate_contract("NormalizeFailure", item.failure.model_dump(mode="json")),
        )
        for item in failures
    )
    sources = [r.source_record_id for r in checked_records] + [
        f.source_record_id for f in checked_failures
    ]
    if len(sources) != len(set(sources)):
        raise DuplicateRecordError("a source record has more than one outcome in the batch")
    return tuple(checked_records), checked_failures


def check_position(current: int | None, last_seq: int) -> None:
    if current is not None and last_seq < current:
        raise ValueError("normalize position cannot move back")


def check_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")


def check_entity_field(field: str) -> None:
    if field not in ENTITY_FIELDS:
        raise ValueError(f"field must be one of {', '.join(ENTITY_FIELDS)}")


def lookup_value(value: str | None) -> str | None:
    """The form an entity value takes in a lookup column: NUL becomes U+FFFD.

    Log values may hold NUL, which text columns refuse. Only the lookup copy is
    changed; the stored record keeps the original. Lookups compare in this form.
    """
    return None if value is None else value.replace("\x00", "\ufffd")


def retention_cutoff(now: int, retention_days: int) -> int | None:
    """Source records stored before this time are expired. None: kept forever (0 days)."""
    if retention_days == 0:
        return None
    return now - retention_days * DAY_MS
