"""In-memory Alert/Event store for tests. Passes the same contract tests as PostgreSQL."""

from soc.store.records.base import (
    DuplicateRecordError,
    PurgeResult,
    SaveResult,
    StoredAlert,
    StoredSource,
    UnknownRecordError,
    UnknownSourceError,
)
from soc.store.records.checks import (
    check_alert_record,
    check_entity_field,
    check_event_record,
    check_limit,
    check_merge,
    check_normalize_batch,
    check_position,
    check_source_records,
    check_window,
    lookup_value,
    merged_alert,
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
        self._failures = {}  # source_record_id -> NormalizeFailure
        self._positions = {}
        self._branch_position = None
        self._merges = {}  # duplicate_alert_id -> target_alert_id
        self._representatives = {}  # alert_id -> (dedup_key, first_seen)
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
        if any(r.source_record_id == record.source_record_id for r in table.values()):
            raise DuplicateRecordError(f"{record.source_record_id} already has a result")
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

    def load_normalize_position(self, kind):
        return self._positions.get(kind)

    def save_normalize_batch(self, kind, records, failures, last_seq):
        records, failures = check_normalize_batch(kind, records, failures)
        check_position(self._positions.get(kind), last_seq)
        table, id_field = (
            (self._alerts, "alert_id") if kind == "alert" else (self._events, "event_id")
        )
        done = {r.source_record_id for r in table.values()} | set(self._failures)
        for item in (*records, *failures):
            source = self._sources.get(item.source_record_id)
            if source is None or source.record.kind != kind:
                raise UnknownSourceError(f"a {kind} batch points at a missing {kind} source")
            if item.source_record_id in done:
                raise DuplicateRecordError("a source record in the batch already has an outcome")
        if any(getattr(r, id_field) in table for r in records):
            raise DuplicateRecordError("a record ID in the batch is already stored")
        for record in records:
            table[getattr(record, id_field)] = record
        for item in failures:
            self._failures[item.source_record_id] = item.failure
        self._positions[kind] = last_seq

    def get_normalize_failure(self, source_record_id):
        return self._failures.get(source_record_id)

    def list_alert_records(self, after_seq, limit):
        check_limit(limit)
        after = after_seq or 0
        found = [
            StoredAlert(self._sources[r.source_record_id].seq, r) for r in self._alerts.values()
        ]
        found = [s for s in found if s.seq > after]
        return tuple(sorted(found, key=lambda s: s.seq)[:limit])

    def load_branch_position(self):
        return self._branch_position

    def save_branch_position(self, last_seq):
        check_position(self._branch_position, last_seq, "branch")
        self._branch_position = last_seq

    def merge_duplicate(self, target_alert_id, duplicate_alert_id, seen_at):
        check_merge(target_alert_id, duplicate_alert_id)
        target = self._alerts.get(target_alert_id)
        if target is None or duplicate_alert_id not in self._alerts:
            raise UnknownRecordError("both alerts must be stored")
        if duplicate_alert_id in self._merges:
            return False
        self._alerts[target_alert_id] = merged_alert(target, seen_at)
        self._merges[duplicate_alert_id] = target_alert_id
        return True

    def save_dedup_representative(self, alert_id, dedup_key, first_seen):
        if alert_id not in self._alerts:
            raise UnknownRecordError("the representative alert must be stored")
        if alert_id in self._representatives:
            return False
        self._representatives[alert_id] = (dedup_key, first_seen)
        return True

    def find_dedup_representative(self, dedup_key, at, window_ms, exclude_alert_id=None):
        check_window(window_ms)
        found = sorted(
            (first_seen, alert_id)
            for alert_id, (key, first_seen) in self._representatives.items()
            if key == dedup_key
            and alert_id != exclude_alert_id
            and first_seen <= at < first_seen + window_ms
        )
        return found[0][1] if found else None

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
        referenced |= set(self._failures)
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
