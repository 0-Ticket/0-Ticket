"""Shared contract tests every Alert/Event store must pass (boxes 6, 7, K8, K9, K67).

Subclass ``RecordStoreContract`` in a ``Test*`` class and provide ``make_store``:
a function ``make_store(retention_days=0, clock=...)`` returning a fresh, empty
store. The in-memory fake and the PostgreSQL store use it; a new backend reuses it.
"""

import json
from pathlib import Path

import pytest

from soc.contracts import ContractValidationError, SiemAlert, validate_contract
from soc.ingest.connector import source_record_id
from soc.store.records.base import (
    DuplicateRecordError,
    PurgeResult,
    SaveResult,
    UnknownSourceError,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DAY_MS = 86_400_000
NOW = 1_800_000_000_000
CURSOR_KEY = "fake"


def load_c2():
    data = json.loads((FIXTURES / "ingest" / "expected_c2.json").read_text(encoding="utf-8"))
    return [validate_contract("SiemAlert", item) for item in data]


def load_alert_records():
    data = json.loads((FIXTURES / "store" / "alert_records.json").read_text(encoding="utf-8"))
    return [validate_contract("AlertRecord", item) for item in data]


def load_event_records():
    data = json.loads((FIXTURES / "store" / "event_records.json").read_text(encoding="utf-8"))
    return [validate_contract("EventRecord", item) for item in data]


def c2(kind, scenario, fields):
    content = {"kind": kind, "scenario": scenario, "raw_ids": [], "fields": fields}
    return validate_contract(
        "SiemAlert", {**content, "source_record_id": source_record_id(content)}
    )


def dump(model):
    return model.model_dump(mode="json")


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class RecordStoreContract:
    @pytest.fixture
    def store(self, make_store):
        return make_store()

    # Source records (C2): stored as they came, once.

    def test_saved_source_record_is_returned_unchanged(self, store):
        items = load_c2()
        assert store.save_source_records(items, CURSOR_KEY, "c1") == SaveResult(len(items), 0)
        for item in items:
            stored = store.get_source_record(item.source_record_id)
            assert isinstance(stored, SiemAlert)
            assert dump(stored) == dump(item)

    def test_unknown_source_record_is_none(self, store):
        assert store.get_source_record("src_" + "0" * 64) is None

    def test_same_source_record_id_is_not_stored_twice(self, store):
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        assert store.save_source_records(items, CURSOR_KEY, "c2") == SaveResult(0, len(items))
        assert len(store.list_source_records("alert", None, 100)) == 2
        assert len(store.list_source_records("event", None, 100)) == 4

    def test_duplicate_inside_one_batch_is_stored_once(self, store):
        item = load_c2()[0]
        assert store.save_source_records([item, item], CURSOR_KEY, "c1") == SaveResult(1, 1)

    def test_item_whose_id_is_not_its_content_hash_is_rejected(self, store):
        good = load_c2()[0]
        forged = SiemAlert.model_validate({**dump(good), "source_record_id": "src_" + "0" * 64})
        with pytest.raises(ContractValidationError) as caught:
            store.save_source_records([good, forged], CURSOR_KEY, "c1")
        assert caught.value.path == "/source_record_id"
        # Nothing of the failed batch is kept, the cursor included.
        assert store.get_source_record(good.source_record_id) is None
        assert store.load_cursor(CURSOR_KEY) is None

    def test_odd_characters_survive_storage(self, store):
        item = c2("event", "odd", {"message": "nul\u0000 tab\t emoji \U0001f600 ‮", "n": 1.5})
        store.save_source_records([item], CURSOR_KEY, "c1")
        assert dump(store.get_source_record(item.source_record_id)) == dump(item)

    def test_list_source_records_pages_by_kind_in_arrival_order(self, store):
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        events = [item for item in items if item.kind == "event"]
        first = store.list_source_records("event", None, 3)
        rest = store.list_source_records("event", first[-1].seq, 3)
        assert [s.record.source_record_id for s in first + rest] == [
            item.source_record_id for item in events
        ]
        assert store.list_source_records("event", rest[-1].seq, 3) == ()
        assert all(s.ingested_at == NOW for s in first + rest)

    def test_limit_below_one_is_rejected(self, store):
        with pytest.raises(ValueError, match="limit"):
            store.list_source_records("alert", None, 0)

    # Cursor: saved with the batch, per key.

    def test_cursor_is_saved_with_the_batch(self, store):
        assert store.load_cursor(CURSOR_KEY) is None
        store.save_source_records(load_c2()[:2], CURSOR_KEY, "after-2")
        assert store.load_cursor(CURSOR_KEY) == "after-2"
        store.save_source_records([], CURSOR_KEY, "after-2-again")
        assert store.load_cursor(CURSOR_KEY) == "after-2-again"
        assert store.load_cursor("other") is None

    # Normalized results (C5, C13): apart from the source, pointing at it.

    def test_normalized_records_point_to_their_source(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        for record in load_alert_records():
            store.save_alert_record(record)
            assert dump(store.get_alert_record(record.alert_id)) == dump(record)
            assert store.get_source_record(record.source_record_id).kind == "alert"
        for record in load_event_records():
            store.save_event_record(record)
            assert dump(store.get_event_record(record.event_id)) == dump(record)
            assert store.get_source_record(record.source_record_id).kind == "event"

    def test_unknown_normalized_record_is_none(self, store):
        assert store.get_alert_record("al_missing") is None
        assert store.get_event_record("ev_missing") is None

    def test_record_without_source_is_rejected(self, store):
        with pytest.raises(UnknownSourceError):
            store.save_alert_record(load_alert_records()[0])
        with pytest.raises(UnknownSourceError):
            store.save_event_record(load_event_records()[0])

    def test_record_pointing_at_the_other_kind_is_rejected(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        alert = load_alert_records()[0]
        event = load_event_records()[0]
        with pytest.raises(UnknownSourceError):
            store.save_alert_record(
                alert.model_copy(update={"source_record_id": event.source_record_id})
            )
        with pytest.raises(UnknownSourceError):
            store.save_event_record(
                event.model_copy(update={"source_record_id": alert.source_record_id})
            )
        assert store.get_alert_record(alert.alert_id) is None
        assert store.get_event_record(event.event_id) is None

    def test_same_record_id_twice_is_rejected(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        alert = load_alert_records()[0]
        store.save_alert_record(alert)
        with pytest.raises(DuplicateRecordError):
            store.save_alert_record(alert)
        event = load_event_records()[0]
        store.save_event_record(event)
        with pytest.raises(DuplicateRecordError):
            store.save_event_record(event)

    def test_invalid_normalized_record_is_rejected(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        broken = load_alert_records()[0].model_copy(update={"severity_id": 9})
        with pytest.raises(ContractValidationError):
            store.save_alert_record(broken)
        assert store.get_alert_record(broken.alert_id) is None

    def test_saving_normalized_results_leaves_sources_unchanged(self, store):
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        for record in load_alert_records():
            store.save_alert_record(record)
        for record in load_event_records():
            store.save_event_record(record)
        for item in items:
            assert dump(store.get_source_record(item.source_record_id)) == dump(item)

    def test_find_records_by_entity_and_time(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        wpscan, sqli = load_alert_records()
        index, wplogin = load_event_records()
        for record in (sqli, wpscan):
            store.save_alert_record(record)
        for record in (wplogin, index):
            store.save_event_record(record)

        def alert_ids(*args):
            return [r.alert_id for r in store.find_alert_records(*args)]

        def event_ids(*args):
            return [r.event_id for r in store.find_event_records(*args)]

        attacker, start, end = "198.51.100.23", wpscan.time, sqli.time
        assert alert_ids("src_ip", attacker, 0, NOW, 10) == [wpscan.alert_id, sqli.alert_id]
        assert alert_ids("src_ip", attacker, start, end, 10) == [wpscan.alert_id]  # end excluded
        assert alert_ids("src_ip", attacker, 0, NOW, 1) == [wpscan.alert_id]
        assert alert_ids("dst_ip", "192.0.2.80", end, end + 1, 10) == [sqli.alert_id]
        assert alert_ids("host", "web-01", 0, NOW, 10) == [wpscan.alert_id, sqli.alert_id]
        assert alert_ids("src_ip", "203.0.113.99", 0, NOW, 10) == []
        assert event_ids("host", "web-01", 0, NOW, 10) == [index.event_id, wplogin.event_id]
        assert event_ids("src_ip", attacker, 0, NOW, 10) == [wplogin.event_id]
        assert event_ids("dst_ip", attacker, 0, NOW, 10) == []

    def test_find_rejects_other_fields_and_bad_limits(self, store):
        with pytest.raises(ValueError, match="field"):
            store.find_alert_records("user", "x", 0, NOW, 10)
        with pytest.raises(ValueError, match="field"):
            store.find_event_records("http_url", "x", 0, NOW, 10)
        with pytest.raises(ValueError, match="limit"):
            store.find_event_records("host", "x", 0, NOW, 0)

    # Retention: setting, forever by default, never under a normalized result.

    def test_default_retention_keeps_everything(self, make_store):
        clock = Clock(NOW - 10_000 * DAY_MS)
        store = make_store(clock=clock)
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        assert store.purge_expired(NOW) == PurgeResult(deleted=0, skipped=0)
        assert len(store.list_source_records("event", None, 100)) == 4

    def test_retention_purges_old_sources_but_keeps_referenced_ones(self, make_store):
        clock = Clock(NOW - 31 * DAY_MS)
        store = make_store(retention_days=30, clock=clock)
        old = load_c2()
        store.save_source_records(old, CURSOR_KEY, "c1")
        store.save_alert_record(load_alert_records()[0])
        store.save_event_record(load_event_records()[0])
        clock.now = NOW - DAY_MS
        new = c2("event", "fresh", {"message": "recent"})
        store.save_source_records([new], CURSOR_KEY, "c2")

        assert store.purge_expired(NOW) == PurgeResult(deleted=4, skipped=2)
        kept = {
            s.record.source_record_id
            for k in ("alert", "event")
            for s in store.list_source_records(k, None, 100)
        }
        assert kept == {
            load_alert_records()[0].source_record_id,
            load_event_records()[0].source_record_id,
            new.source_record_id,
        }
        assert store.purge_expired(NOW) == PurgeResult(deleted=0, skipped=2)
