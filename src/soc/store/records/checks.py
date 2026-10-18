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

from .base import ENTITY_FIELDS

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


def check_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")


def check_entity_field(field: str) -> None:
    if field not in ENTITY_FIELDS:
        raise ValueError(f"field must be one of {', '.join(ENTITY_FIELDS)}")


def retention_cutoff(now: int, retention_days: int) -> int | None:
    """Source records stored before this time are expired. None: kept forever (0 days)."""
    if retention_days == 0:
        return None
    return now - retention_days * DAY_MS
