"""Box 4 runner: reads sources in order, normalizes, joins lookups, saves with its position."""

import pytest
from fake_store import FakeRecordStore
from lookup_fakes import WEB_01, FakeLookup
from normalize_fixtures import NORMALIZE, NOW, dump, fake_waf_c2, load_ait_c2, make_c2, read_json

from soc.contracts import AlertRecord, EventRecord
from soc.normalize.alias import load_alias_tables
from soc.normalize.lookup.enricher import LookupEnricher
from soc.normalize.lookup.none import NoneLookup
from soc.normalize.normalizer import Normalizer
from soc.normalize.runner import alert_id_for, event_id_for, normalize_once, normalize_pending


def clock():
    return NOW


@pytest.fixture
def store():
    store = FakeRecordStore()
    store.save_source_records(load_ait_c2(), "direct", "c1")
    return store


@pytest.fixture
def normalizer():
    return Normalizer(load_alias_tables(None), 16_384)


@pytest.fixture
def enricher():
    return LookupEnricher(NoneLookup())


def run(store, normalizer, enricher, kind, batch_size=100):
    return normalize_once(store, normalizer, enricher, kind, batch_size, clock)


def test_alert_record_gets_id_count_and_seen_times(store, normalizer, enricher):
    result = run(store, normalizer, enricher, "alert")
    assert (result.read, result.normalized, result.failed) == (2, 2, 0)
    expected = read_json(NORMALIZE / "expected_c3.json")
    for row in expected:
        source_id = row["source_record_id"]
        record = store.get_alert_record(alert_id_for(source_id))
        assert isinstance(record, AlertRecord)
        assert record.alert_id == "al_" + source_id.removeprefix("src_")
        assert record.source_record_id == source_id
        assert record.count == 1
        assert record.first_seen == record.last_seen == row["c3"]["time"]
        assert (record.src_asset, record.dst_asset, record.user_info) == (None, None, None)
        c3_part = {key: value for key, value in dump(record).items() if key in row["c3"]}
        assert c3_part == row["c3"]


def test_events_are_saved_as_expected_c13(store, normalizer, enricher):
    result = run(store, normalizer, enricher, "event")
    assert (result.read, result.normalized, result.failed) == (4, 4, 0)
    for expected in read_json(NORMALIZE / "expected_c13.json"):
        record = store.get_event_record(expected["event_id"])
        assert isinstance(record, EventRecord)
        assert dump(record) == expected
        assert expected["event_id"] == event_id_for(expected["source_record_id"])


def test_lookup_results_are_joined(store, normalizer):
    enricher = LookupEnricher(FakeLookup({"192.0.2.80": WEB_01}))
    run(store, normalizer, enricher, "alert")
    record = store.get_alert_record(alert_id_for(load_ait_c2()[0].source_record_id))
    assert record.dst_asset == WEB_01
    assert record.src_asset is None


def test_runner_resumes_from_saved_position(store, normalizer, enricher):
    first = run(store, normalizer, enricher, "event", batch_size=3)
    assert first.read == 3
    second = run(store, normalizer, enricher, "event", batch_size=3)
    assert second.read == 1
    third = run(store, normalizer, enricher, "event", batch_size=3)
    assert third.read == 0
    assert third.last_seq == second.last_seq
    assert store.load_normalize_position("event") == second.last_seq
    assert store.load_normalize_position("alert") is None


def test_runner_does_not_normalize_a_source_twice(store, normalizer, enricher):
    normalize_pending(store, normalizer, enricher, 2, clock)
    again = normalize_pending(store, normalizer, enricher, 2, clock)
    assert [run.read for run in again] == [0, 0]
    late = make_c2(
        "event",
        "ait_apache_access",
        read_json(NORMALIZE.parent / "ingest" / "expected_c2.json")[2]["fields"],
        ["raw_late_1"],
    )
    store.save_source_records([late], "direct", "c2")
    runs = normalize_pending(store, normalizer, enricher, 2, clock)
    assert sum(run.read for run in runs) == 1
    assert store.get_event_record(event_id_for(late.source_record_id)) is not None


def test_failures_are_stored_with_their_source(store, normalizer, enricher):
    bad = make_c2("alert", "no_such_scenario", {"x": "secretmarker"})
    store.save_source_records([bad], "direct", "c2")
    result = run(store, normalizer, enricher, "alert")
    assert (result.read, result.normalized, result.failed) == (3, 2, 1)
    failure = store.get_normalize_failure(bad.source_record_id)
    assert failure.reason == "unknown_mapping_profile"
    assert failure.failed_at == NOW
    assert "secretmarker" not in str(dump(failure))


def test_overlong_line_fails_and_the_runner_keeps_going(store, enricher):
    long_line = make_c2("event", "ait_apache_access", {"message": "x" * 300})
    store.save_source_records([long_line], "direct", "c2")
    normalizer = Normalizer(load_alias_tables(None), 200)
    runs = normalize_pending(store, normalizer, enricher, 100, clock)
    assert store.get_normalize_failure(long_line.source_record_id).reason == "bad_value"
    assert sum(run.normalized for run in runs) == 6


def test_failed_save_leaves_position_and_records_untouched(store, normalizer, enricher):
    class Exploding(FakeRecordStore):
        def save_normalize_batch(self, *args, **kwargs):
            raise RuntimeError("disk full")

    broken = Exploding()
    broken.save_source_records(load_ait_c2(), "direct", "c1")
    with pytest.raises(RuntimeError):
        run(broken, normalizer, enricher, "alert")
    assert broken.load_normalize_position("alert") is None
    retry = run(store, normalizer, enricher, "alert")
    assert retry.read == 2


def test_empty_store_reads_nothing(normalizer, enricher):
    result = run(FakeRecordStore(), normalizer, enricher, "alert")
    assert (result.read, result.normalized, result.failed, result.last_seq) == (0, 0, 0, None)


def test_extensions_survive_normalize_and_store(enricher):
    store = FakeRecordStore()
    item = fake_waf_c2()
    store.save_source_records([item], "fake", "c1")
    normalizer = Normalizer(load_alias_tables(NORMALIZE / "aliases"), 16_384)
    run(store, normalizer, enricher, "alert")
    record = store.get_alert_record(alert_id_for(item.source_record_id))
    assert record.extensions == {"acme.tenant": "acme-01"}
    assert [r.alert_id for r in store.find_alert_records("host", "web-01", 0, NOW, 10)] == [
        record.alert_id
    ]
