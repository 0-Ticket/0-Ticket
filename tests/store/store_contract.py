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
    SourceFailure,
    UnknownRecordError,
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


def c2(kind, mapping_profile, fields):
    content = {"kind": kind, "mapping_profile": mapping_profile, "raw_ids": [], "fields": fields}
    return validate_contract(
        "SiemAlert", {**content, "source_record_id": source_record_id(content)}
    )


def failure(reason="unknown_scenario", raw_ids=("raw_suricata_eve.jsonl_1",)):
    return validate_contract(
        "NormalizeFailure",
        {
            "mapping_profile": "ait_suricata_alert",
            "raw_ids": list(raw_ids),
            "reason": reason,
            "missing_fields": [],
            "detail": "no alias table for this scenario",
            "failed_at": NOW,
        },
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

    @pytest.mark.parametrize("http_bytes", [0, 1534, None])
    def test_event_http_bytes_round_trip_through_get_and_find(self, store, http_bytes):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        record = load_event_records()[0].model_copy(update={"http_bytes": http_bytes})
        store.save_event_record(record)

        stored = store.get_event_record(record.event_id)
        assert stored is not None
        assert stored.http_bytes == http_bytes

        found = store.find_event_records("host", record.host, record.time, record.time + 1, 10)
        assert len(found) == 1
        assert found[0].http_bytes == http_bytes

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

    def test_nul_in_lookup_value_is_stored_and_kept_in_the_record(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        host = "web\u000001"
        record = load_alert_records()[0].model_copy(update={"host": host, "src_ip": "a\u0000"})
        store.save_alert_record(record)
        stored = store.get_alert_record(record.alert_id)
        assert stored.host == host
        assert dump(stored) == dump(record)
        found = store.find_alert_records("host", host, 0, NOW, 10)
        assert [r.alert_id for r in found] == [record.alert_id]

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

    # Normalization batches (box 4): results, failures and position, together or not at all.

    def test_normalize_position_starts_empty(self, store):
        assert store.load_normalize_position("alert") is None
        assert store.load_normalize_position("event") is None

    def test_normalize_batch_saves_results_failures_and_position(self, store):
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        alert = load_alert_records()[0]
        failed_source = items[1].source_record_id
        store.save_normalize_batch("alert", [alert], [SourceFailure(failed_source, failure())], 7)
        assert dump(store.get_alert_record(alert.alert_id)) == dump(alert)
        assert dump(store.get_normalize_failure(failed_source)) == dump(failure())
        assert store.load_normalize_position("alert") == 7
        assert store.load_normalize_position("event") is None
        store.save_normalize_batch("event", load_event_records(), [], 9)
        assert store.load_normalize_position("event") == 9
        assert store.get_event_record(load_event_records()[0].event_id) is not None

    @pytest.mark.parametrize("reason", ["unknown_scenario", "unknown_mapping_profile"])
    def test_normalize_failure_reasons_round_trip_through_store(self, store, reason):
        source = next(item for item in load_c2() if item.kind == "alert")
        store.save_source_records([source], CURSOR_KEY, "c1")
        result = failure(reason, source.raw_ids)

        store.save_normalize_batch("alert", [], [SourceFailure(source.source_record_id, result)], 1)

        assert dump(store.get_normalize_failure(source.source_record_id)) == dump(result)

    def test_unknown_failure_is_none(self, store):
        assert store.get_normalize_failure("src_" + "0" * 64) is None

    def test_failed_normalize_batch_saves_nothing(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        good, _ = load_alert_records()
        orphan = good.model_copy(
            update={"alert_id": "al_orphan", "source_record_id": "src_" + "f" * 64}
        )
        with pytest.raises(UnknownSourceError):
            store.save_normalize_batch("alert", [good, orphan], [], 5)
        assert store.get_alert_record(good.alert_id) is None
        assert store.load_normalize_position("alert") is None

    def test_failure_for_unknown_or_other_kind_source_is_rejected(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        event_source = load_event_records()[0].source_record_id
        with pytest.raises(UnknownSourceError):
            store.save_normalize_batch("alert", [], [SourceFailure(event_source, failure())], 1)
        with pytest.raises(UnknownSourceError):
            store.save_normalize_batch(
                "alert", [], [SourceFailure("src_" + "e" * 64, failure())], 1
            )
        assert store.get_normalize_failure(event_source) is None
        assert store.load_normalize_position("alert") is None

    def test_second_result_for_one_source_is_rejected(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        alert = load_alert_records()[0]
        store.save_normalize_batch("alert", [alert], [], 1)
        twin = alert.model_copy(update={"alert_id": "al_twin"})
        with pytest.raises(DuplicateRecordError):
            store.save_normalize_batch("alert", [twin], [], 2)
        with pytest.raises(DuplicateRecordError):
            store.save_normalize_batch(
                "alert", [], [SourceFailure(alert.source_record_id, failure())], 2
            )
        assert store.get_alert_record("al_twin") is None
        assert store.load_normalize_position("alert") == 1

    def test_normalize_position_does_not_move_back(self, store):
        store.save_normalize_batch("alert", [], [], 5)
        with pytest.raises(ValueError, match="position"):
            store.save_normalize_batch("alert", [], [], 4)
        assert store.load_normalize_position("alert") == 5

    def test_normalize_batch_checks_kind_and_contracts(self, store):
        store.save_source_records(load_c2(), CURSOR_KEY, "c1")
        with pytest.raises(ValueError, match="kind"):
            store.save_normalize_batch("event", [load_alert_records()[0]], [], 1)
        with pytest.raises(ValueError, match="kind"):
            store.save_normalize_batch("other", [], [], 1)
        broken = load_alert_records()[0].model_copy(update={"severity_id": 9})
        with pytest.raises(ContractValidationError):
            store.save_normalize_batch("alert", [broken], [], 1)
        assert store.load_normalize_position("alert") is None

    def test_source_with_failure_is_not_purged(self, make_store):
        clock = Clock(NOW - 31 * DAY_MS)
        store = make_store(retention_days=30, clock=clock)
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        kept = items[0].source_record_id
        store.save_normalize_batch("alert", [], [SourceFailure(kept, failure())], 1)
        assert store.purge_expired(NOW) == PurgeResult(deleted=5, skipped=1)
        assert store.get_source_record(kept) is not None

    # Entity branching (box 25): alerts in arrival order, a position, duplicate merges.

    def _stored_alerts(self, store):
        """Both sample C5 saved, in the order their sources arrived."""
        items = load_c2()
        store.save_source_records(items, CURSOR_KEY, "c1")
        by_source = {r.source_record_id: r for r in load_alert_records()}
        alerts = [
            by_source[s.record.source_record_id]
            for s in store.list_source_records("alert", None, 100)
        ]
        for alert in reversed(alerts):  # saved out of order: listing follows the source
            store.save_alert_record(alert)
        return alerts

    def test_list_alert_records_follows_source_arrival_order(self, store):
        alerts = self._stored_alerts(store)
        listed = store.list_alert_records(None, 100)
        assert [a.record.alert_id for a in listed] == [a.alert_id for a in alerts]
        sources = store.list_source_records("alert", None, 100)
        assert [a.seq for a in listed] == [s.seq for s in sources]
        assert [dump(a.record) for a in listed] == [dump(a) for a in alerts]

    def test_list_alert_records_pages_after_seq(self, store):
        alerts = self._stored_alerts(store)
        first = store.list_alert_records(None, 1)
        rest = store.list_alert_records(first[-1].seq, 5)
        assert [a.record.alert_id for a in first + rest] == [a.alert_id for a in alerts]
        assert store.list_alert_records(rest[-1].seq, 5) == ()
        with pytest.raises(ValueError, match="limit"):
            store.list_alert_records(None, 0)

    def test_branch_position_starts_empty_and_does_not_move_back(self, store):
        assert store.load_branch_position() is None
        store.save_branch_position(5)
        store.save_branch_position(5)
        assert store.load_branch_position() == 5
        with pytest.raises(ValueError, match="position"):
            store.save_branch_position(4)
        assert store.load_branch_position() == 5
        # Branching and normalization keep separate positions.
        assert store.load_normalize_position("alert") is None

    def test_merge_duplicate_raises_count_and_last_seen_once(self, store):
        target, duplicate = self._stored_alerts(store)
        later = target.last_seen + 60_000
        assert store.merge_duplicate(target.alert_id, duplicate.alert_id, later) is True
        merged = store.get_alert_record(target.alert_id)
        assert (merged.count, merged.first_seen, merged.last_seen) == (
            target.count + 1,
            target.first_seen,
            later,
        )
        # The same duplicate again changes nothing.
        assert store.merge_duplicate(target.alert_id, duplicate.alert_id, later + 1) is False
        assert dump(store.get_alert_record(target.alert_id)) == dump(merged)
        # The duplicate itself is not changed.
        assert dump(store.get_alert_record(duplicate.alert_id)) == dump(duplicate)

    def test_merge_duplicate_keeps_the_later_last_seen(self, store):
        target, duplicate = self._stored_alerts(store)
        store.merge_duplicate(target.alert_id, duplicate.alert_id, target.last_seen - 1)
        merged = store.get_alert_record(target.alert_id)
        assert (merged.count, merged.last_seen) == (target.count + 1, target.last_seen)

    def test_merge_duplicate_needs_two_stored_alerts(self, store):
        target, duplicate = self._stored_alerts(store)
        with pytest.raises(UnknownRecordError):
            store.merge_duplicate("al_missing", duplicate.alert_id, NOW)
        with pytest.raises(UnknownRecordError):
            store.merge_duplicate(target.alert_id, "al_missing", NOW)
        with pytest.raises(ValueError, match="itself"):
            store.merge_duplicate(target.alert_id, target.alert_id, NOW)
        assert dump(store.get_alert_record(target.alert_id)) == dump(target)

    # Duplicate representatives (box 25, #87): one row per representative alert.

    def test_dedup_representative_is_found_inside_its_window(self, store):
        first, _ = self._stored_alerts(store)
        assert store.save_dedup_representative(first.alert_id, "key_a", 1_000) is True
        assert store.find_dedup_representative("key_a", 1_000, 600) == first.alert_id
        assert store.find_dedup_representative("key_a", 1_599, 600) == first.alert_id
        # The window ends before first_seen + window and does not start before first_seen.
        assert store.find_dedup_representative("key_a", 1_600, 600) is None
        assert store.find_dedup_representative("key_a", 999, 600) is None
        assert store.find_dedup_representative("key_b", 1_000, 600) is None

    def test_dedup_representative_is_saved_once(self, store):
        first, _ = self._stored_alerts(store)
        assert store.save_dedup_representative(first.alert_id, "key_a", 1_000) is True
        # Saving it again (a rerun after a stop) changes nothing.
        assert store.save_dedup_representative(first.alert_id, "key_a", 1_000) is False
        assert store.save_dedup_representative(first.alert_id, "key_b", 5_000) is False
        assert store.find_dedup_representative("key_a", 1_000, 600) == first.alert_id
        assert store.find_dedup_representative("key_b", 5_000, 600) is None

    def test_earliest_dedup_representative_wins_and_self_is_left_out(self, store):
        first, second = self._stored_alerts(store)
        store.save_dedup_representative(second.alert_id, "key_a", 1_200)
        store.save_dedup_representative(first.alert_id, "key_a", 1_000)
        assert store.find_dedup_representative("key_a", 1_300, 600) == first.alert_id
        # Past the first window, only the later representative still covers the time.
        assert store.find_dedup_representative("key_a", 1_700, 600) == second.alert_id
        # An alert is never its own duplicate.
        assert store.find_dedup_representative("key_a", 1_300, 600, first.alert_id) == (
            second.alert_id
        )
        assert store.find_dedup_representative("key_a", 1_700, 600, second.alert_id) is None

    def test_dedup_representative_needs_a_stored_alert_and_a_window(self, store):
        self._stored_alerts(store)
        with pytest.raises(UnknownRecordError):
            store.save_dedup_representative("al_missing", "key_a", 1_000)
        assert store.find_dedup_representative("key_a", 1_000, 600) is None
        with pytest.raises(ValueError, match="window"):
            store.find_dedup_representative("key_a", 1_000, 0)
