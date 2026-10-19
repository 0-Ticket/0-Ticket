"""Duplicate alerts (box 25): the same rule and entities again within the window.

An alert is a duplicate of a *first alert* when both have the same ``rule_id``
and the same entity set (``alert_entities``), and the alert's time falls within
``dedup_window_minutes`` from the first alert's ``first_seen``. The window is
fixed to the first alert: once it ends, the next such alert is a new first
alert. A first alert is an alert already branched on any path but
``deduplicated``; the earliest one wins.

Candidates are read by the alert's first lookup field (``src_ip``, ``dst_ip``,
``host``) in time order, oldest first, so the earliest first alert is read
before ``dedup_scan_limit`` cuts the list. An alert with none of those fields
is never a duplicate.
"""

from soc.contracts import AlertRecord
from soc.l1.entities import alert_entities
from soc.store.branches.base import BranchStore
from soc.store.records.base import ENTITY_FIELDS, RecordStore

MINUTE_MS = 60_000


def find_first_alert(
    alert: AlertRecord,
    records: RecordStore,
    branches: BranchStore,
    window_minutes: int,
    scan_limit: int,
) -> AlertRecord | None:
    """The first alert ``alert`` duplicates, or None."""
    field = next((f for f in ENTITY_FIELDS if _present(getattr(alert, f))), None)
    if field is None:
        return None
    window_ms = window_minutes * MINUTE_MS
    entities = _entity_set(alert)
    # first_seen > time - window, and time <= alert time (find's end is exclusive).
    candidates = records.find_alert_records(
        field, getattr(alert, field), alert.time - window_ms + 1, alert.time + 1, scan_limit
    )
    for candidate in candidates:
        if (
            candidate.alert_id == alert.alert_id
            or candidate.rule_id != alert.rule_id
            or not candidate.first_seen <= alert.time < candidate.first_seen + window_ms
            or _entity_set(candidate) != entities
        ):
            continue
        branched = branches.get("alert", candidate.alert_id)
        if branched is not None and branched.path != "deduplicated":
            return candidate
    return None


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _entity_set(alert: AlertRecord) -> frozenset[tuple[str, str]]:
    return frozenset((e["type"], e["value"]) for e in alert_entities(alert))
