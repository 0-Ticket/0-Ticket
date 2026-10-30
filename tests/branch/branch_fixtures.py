"""Sample alerts for box 25, stored in a fake record store in fixture order."""

import json
from pathlib import Path

from soc.contracts import validate_contract
from soc.ingest.connector import source_record_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "branch"
T = 1791849600000
MINUTE = 60_000


def alert_data():
    return json.loads((FIXTURES / "alerts.json").read_text(encoding="utf-8"))


def source_for(alert_id):
    content = {
        "kind": "alert",
        "mapping_profile": "branch_test",
        "raw_ids": [],
        "fields": {"alert": alert_id},
    }
    return validate_contract(
        "SiemAlert", {**content, "source_record_id": source_record_id(content)}
    )


def store_alerts(records, items):
    """Save each C5 dict with its own C2 source, in list order (= arrival order)."""
    sources = [source_for(item["alert_id"]) for item in items]
    records.save_source_records(sources, "test", None)
    saved = []
    for source, item in zip(sources, items, strict=True):
        alert = validate_contract(
            "AlertRecord", {**item, "source_record_id": source.source_record_id}
        )
        records.save_alert_record(alert)
        saved.append(alert)
    return saved


def at(item, alert_id, minutes, **changes):
    """A copy of a C5 dict with a new ID and time ``minutes`` after T."""
    time = T + int(minutes * MINUTE)
    return {
        **item,
        "alert_id": alert_id,
        "time": time,
        "first_seen": time,
        "last_seen": time,
        **changes,
    }
