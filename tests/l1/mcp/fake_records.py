"""Read-only Alert/Event records for the MCP tool tests (boxes 19, 28, 31, 42).

The internal data and Web tools only read, so this fake serves the three read
methods they use and nothing else: a tool that tried to write would fail here.
Field and limit checks come from the store's own ``checks``, so the fake answers
a bad query exactly as PostgreSQL does.
"""

import json
from pathlib import Path

from soc.contracts import validate_contract
from soc.store.records.checks import check_entity_field, check_limit, lookup_value

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "l1" / "mcp"
ALERTS_FILE = FIXTURES / "internal_records.json"
EVENTS_FILE = FIXTURES / "http_flow_events.json"


def _load(path, contract):
    return tuple(
        validate_contract(contract, item) for item in json.loads(path.read_text(encoding="utf-8"))
    )


def fixture_alerts():
    return _load(ALERTS_FILE, "AlertRecord")


def fixture_events():
    return _load(EVENTS_FILE, "EventRecord")


class FakeReadOnlyRecords:
    def __init__(self, alerts=None, events=None):
        self.alerts = fixture_alerts() if alerts is None else tuple(alerts)
        self.events = fixture_events() if events is None else tuple(events)
        self.queries: list[tuple] = []

    def find_alert_records(self, field, value, time_from, time_to, limit):
        return self._find(self.alerts, "alert_id", field, value, time_from, time_to, limit)

    def find_event_records(self, field, value, time_from, time_to, limit):
        return self._find(self.events, "event_id", field, value, time_from, time_to, limit)

    def get_alert_record(self, alert_id):
        self.queries.append(("get_alert_record", alert_id))
        return next((record for record in self.alerts if record.alert_id == alert_id), None)

    def get_event_record(self, event_id):
        self.queries.append(("get_event_record", event_id))
        return next((record for record in self.events if record.event_id == event_id), None)

    def _find(self, records, id_field, field, value, time_from, time_to, limit):
        self.queries.append((id_field, field, value, time_from, time_to, limit))
        check_entity_field(field)
        check_limit(limit)
        found = [
            record
            for record in records
            if lookup_value(getattr(record, field)) == lookup_value(value)
            and time_from <= record.time < time_to
        ]
        found.sort(key=lambda record: (record.time, getattr(record, id_field)))
        return tuple(found[:limit])
