"""Duplicate alerts (boxes 10-13): the same rule and entities again within the window.

An alert is a duplicate of a *first alert* when both have the same ``rule_id``
and the same entity set (``alert_entities``, no direction: the same two IPs
swapped are the same set), and the alert's time falls within
``dedup_window_minutes`` from the first alert's ``first_seen``. The window is
fixed to the first alert: once it ends, the next such alert is a new first
alert. A first alert is an alert already branched on any path but
``deduplicated``; the earliest one wins. An alert with no entity at all is never
a duplicate.

Every first alert is saved in the store's representative table under
``dedup_key`` (#87), so finding one is a single indexed lookup, however many
alerts share an IP.
"""

import hashlib
import json

from soc.contracts import AlertRecord
from soc.l1.entities import alert_entities
from soc.store.records.base import RecordStore

MINUTE_MS = 60_000


def dedup_key(alert: AlertRecord) -> str | None:
    """Hash of the rule and the entity set; None for an alert without entities.

    The key holds no log text, only its hash, so any value fits the column.
    """
    entities = sorted({(e["type"], e["value"]) for e in alert_entities(alert)})
    if not entities:
        return None
    text = json.dumps([alert.rule_id, entities], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_first_alert_id(
    alert: AlertRecord, key: str | None, records: RecordStore, window_minutes: int
) -> str | None:
    """The ID of the first alert ``alert`` duplicates, or None. ``key`` is its ``dedup_key``."""
    if key is None:
        return None
    return records.find_dedup_representative(
        key, alert.time, window_minutes * MINUTE_MS, alert.alert_id
    )
