"""In-memory Alert/Event store for tests. Passes the same contract tests as PostgreSQL."""

from soc.store.records.base import (
    DuplicateRecordError,
    PurgeResult,
    SaveResult,
    StoredSource,
    UnknownSourceError,
)
from soc.store.records.checks import (
    check_alert_record,
    check_entity_field,
    check_event_record,
    check_limit,
    check_source_records,
    lookup_value,
    retention_cutoff,
)


class FakeRecordStore:
    def __init__(self, retention_days=0, clock=None):
        self.retention_days = retention_days
        self._clock = clock or (lambda: 0)
        self._sources = {}  # source_record_id -> StoredSource
        self._cursors = {}
        self._alerts = {}
        self._events = {}
        self._seq = 0
        self.closed = False

    def save_source_records(self, items, cursor_key, next_cursor):
        items = check_source_records(items)
        inserted = duplicates = 0
        now = self._clock()
        for item in items:
            if item.source_record_id in self._sources:
                duplicates += 1
                continue
            self._seq += 1
            self._sources[item.source_record_id] = StoredSource(self._seq, now, item)
            inserted += 1
        self._cursors[cursor_key] = next_cursor
        return SaveResult(inserted, duplicates)

    def load_cursor(self, cursor_key):
        return self._cursors.get(cursor_key)

    def get_source_record(self, source_record_id):
        stored = self._sources.get(source_record_id)
        return stored.record if stored else None

    def list_source_records(self, kind, after_seq, limit):
        check_limit(limit)
        after = after_seq or 0
        found = [s for s in self._sources.values() if s.record.kind == kind and s.seq > after]
        return tuple(sorted(found, key=lambda s: s.seq)[:limit])

    def _save(self, table, record_id, record, kind):
        source = self._sources.get(record.source_record_id)
        if source is None or source.record.kind != kind:
            raise UnknownSourceError(f"no {kind} source record for {record_id}")
        if record_id in table:
            raise DuplicateRecordError(f"{record_id} is already stored")
        table[record_id] = record

    def save_alert_record(self, record):
        record = check_alert_record(record)
        self._save(self._alerts, record.alert_id, record, "alert")

    def save_event_record(self, record):
        record = check_event_record(record)
        self._save(self._events, record.event_id, record, "event")

    def get_alert_record(self, alert_id):
        return self._alerts.get(alert_id)

    def get_event_record(self, event_id):
        return self._events.get(event_id)

    @staticmethod
    def _find(table, id_field, field, value, time_from, time_to, limit):
        check_entity_field(field)
        check_limit(limit)
        found = [
            r
            for r in table.values()
            if lookup_value(getattr(r, field)) == lookup_value(value)
            and time_from <= r.time < time_to
        ]
        return tuple(sorted(found, key=lambda r: (r.time, getattr(r, id_field)))[:limit])

    def find_alert_records(self, field, value, time_from, time_to, limit):
        return self._find(self._alerts, "alert_id", field, value, time_from, time_to, limit)

    def find_event_records(self, field, value, time_from, time_to, limit):
        return self._find(self._events, "event_id", field, value, time_from, time_to, limit)

    def purge_expired(self, now):
        cutoff = retention_cutoff(now, self.retention_days)
        if cutoff is None:
            return PurgeResult(0, 0)
        referenced = {r.source_record_id for r in (*self._alerts.values(), *self._events.values())}
        deleted = skipped = 0
        for source_id, stored in list(self._sources.items()):
            if stored.ingested_at >= cutoff:
                continue
            if source_id in referenced:
                skipped += 1
            else:
                del self._sources[source_id]
                deleted += 1
        return PurgeResult(deleted, skipped)

    def close(self):
        self.closed = True


def fake_records_factory(settings, environ):
    return FakeRecordStore(settings.store.raw_retention_days)
