"""격리된 hit가 페이지 체크포인트·실행 건수와 함께 저장되는지 확인한다."""

import copy

import pytest
from fake_elk import EVENTS, FakeElk, FakeStore, fixture, make_settings, respond

from soc.ingest import run as run_module

EVENT_CP = ("elk-test", "event", "logs-web-*")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(run_module, "store", fake)
    return fake


def run_with(fake_store: FakeStore, fake: FakeElk, *, page_size: int = 2, sleep=None):
    settings = make_settings(EVENTS, page_size=page_size)
    with fake.client() as client:
        (result,) = run_module.run(settings, None, client, sleep=sleep or (lambda _: None))
    return result


def test_nonfinite_hit_is_quarantined_while_normal_hit_and_checkpoint_save(
    store: FakeStore,
) -> None:
    fake = FakeElk({"logs-web-*": ["elk_quarantine_page.json", "elk_empty.json"]})

    result = run_with(store, fake)

    assert (result.pages, result.inserted, result.quarantined, result.failure) == (1, 1, 1, None)
    assert len(store.records) == 1
    normal = next(iter(store.records.values()))
    assert normal["siem_ref"] == "logs-web-000001/normal-1"
    (quarantine,) = store.quarantines.values()
    assert quarantine["reason_code"] == "non_finite"
    assert quarantine["siem_ref"].startswith("synthetic:v1:")
    assert "NaN" in quarantine["original_text"]
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754060000}
    assert store.runs[0]["quarantined"] == 1


def test_persistent_middle_bad_sort_is_quarantined_and_page_continues(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_bad_sort_middle.json"] * 3 + ["elk_empty.json"]})
    delays: list[float] = []

    result = run_with(store, fake, page_size=3, sleep=delays.append)

    assert (result.pages, result.inserted, result.quarantined, result.failure) == (1, 2, 1, None)
    assert fake.calls().count("POST /_search") == 4
    assert delays == [1.0, 1.0]
    assert [row["reason_code"] for row in store.quarantines.values()] == ["sort_value"]
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754060000}


def test_persistent_last_bad_sort_commits_rows_without_advancing_checkpoint(
    store: FakeStore,
) -> None:
    store.checkpoints[EVENT_CP] = {
        "siem_profile": "elk-test",
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": {"time_ms": 1793753940000},
        "updated_at": 1793753940000,
    }
    fake = FakeElk({"logs-web-*": ["elk_bad_sort_last.json"] * 3})
    delays: list[float] = []

    result = run_with(store, fake, sleep=delays.append)

    assert (result.pages, result.inserted, result.quarantined, result.failure) == (
        1,
        1,
        1,
        "sort_value",
    )
    assert fake.calls().count("POST /_search") == 3
    assert delays == [1.0, 1.0]
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793753940000}
    assert store.runs[0]["outcome"] == "sort_value"


def test_non_object_hit_is_preserved_as_hit_ref_and_last_member_stops_run(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_non_object_last.json"] * 3})

    result = run_with(store, fake)

    assert (result.inserted, result.quarantined, result.failure) == (1, 1, "sort_value")
    (quarantine,) = store.quarantines.values()
    assert quarantine["reason_code"] == "hit_ref"
    assert quarantine["original_text"] == '["synthetic", "raw", "member"]'
    assert EVENT_CP not in store.checkpoints
    assert fake.calls().count("POST /_search") == 3


def test_persistent_middle_non_object_hit_retries_then_continues(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_non_object_hits.json"] * 3 + ["elk_empty.json"]})
    delays: list[float] = []

    result = run_with(store, fake, sleep=delays.append)

    assert (result.inserted, result.quarantined, result.failure) == (1, 1, None)
    assert fake.calls().count("POST /_search") == 4
    assert delays == [1.0, 1.0]
    (quarantine,) = store.quarantines.values()
    assert quarantine["reason_code"] == "hit_ref"
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754060000}


def test_bad_identifiers_are_quarantined_with_synthetic_keys(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_bad_references.json", "elk_empty.json"]})

    result = run_with(store, fake, page_size=4)

    assert (result.inserted, result.quarantined, result.failure) == (0, 4, None)
    assert {row["reason_code"] for row in store.quarantines.values()} == {"hit_ref"}
    assert all(row["siem_ref"].startswith("synthetic:v1:") for row in store.quarantines.values())
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754003000}


def test_depth_over_100_is_quarantined_and_original_is_serialized(store: FakeStore) -> None:
    nested = "leaf"
    for _ in range(99):
        nested = {"down": nested}
    hit = {
        "_index": "logs-web-000001",
        "_id": "deep-1",
        "sort": [1793754000000, 11],
        "_source": {"nested": nested},
    }
    page = {"pit_id": "pit-deep", "hits": {"hits": [hit]}}
    fake = FakeElk({"logs-web-*": [respond(200, page)]})

    result = run_with(store, fake)

    assert (result.inserted, result.quarantined, result.failure) == (0, 1, None)
    (quarantine,) = store.quarantines.values()
    assert quarantine["reason_code"] == "depth_exceeded"
    assert '"leaf"' in quarantine["original_text"]


def test_raw_record_contract_rejection_becomes_quarantine(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_record = run_module._raw_record

    def rejected(settings, source, hit, fetched_at):
        record = raw_record(settings, source, hit, fetched_at)
        record["kind"] = "log"
        return record

    monkeypatch.setattr(run_module, "_raw_record", rejected)
    fake = FakeElk({"logs-web-*": ["elk_events_page2.json"]})

    result = run_with(store, fake)

    assert (result.inserted, result.quarantined, result.failure) == (0, 1, None)
    (quarantine,) = store.quarantines.values()
    assert quarantine["reason_code"] == "contract_rejected"


def test_transient_and_bad_sort_budgets_allow_nine_search_requests(store: FakeStore) -> None:
    page = fixture("elk_bad_sort_middle.json")
    answers = []
    for attempt in range(3):
        answers.extend(
            [
                respond(500, {"error": "hidden"}),
                respond(429, {"error": "hidden"}),
                respond(200, {**copy.deepcopy(page), "pit_id": f"pit-page-{attempt}"}),
            ]
        )
    answers.append("elk_empty.json")
    fake = FakeElk({"logs-web-*": answers})
    delays: list[float] = []

    result = run_with(store, fake, page_size=3, sleep=delays.append)

    bodies = fake.search_bodies()
    assert (result.inserted, result.quarantined, result.failure) == (2, 1, None)
    assert len(bodies) == 10  # page 1의 아홉 요청과 뒤의 빈 페이지 조회
    assert [body["pit"]["id"] for body in bodies[:3]] == ["pit-logs-web-*"] * 3
    assert [body["pit"]["id"] for body in bodies[3:6]] == ["pit-page-0"] * 3
    assert [body["pit"]["id"] for body in bodies[6:9]] == ["pit-page-1"] * 3
    assert all("search_after" not in body for body in bodies[:9])
    assert bodies[9]["search_after"] == [1793754060000, 13]
    assert delays == [1.0] * 8


def test_duplicate_quarantine_does_not_increment_new_count(store: FakeStore) -> None:
    searches = {"logs-web-*": ["elk_quarantine_page.json", "elk_empty.json"]}
    first = run_with(store, FakeElk(searches))
    second = run_with(store, FakeElk(searches))

    assert (first.inserted, first.quarantined) == (1, 1)
    assert (second.inserted, second.quarantined) == (0, 0)
    assert len(store.quarantines) == 1
    assert [row["quarantined"] for row in store.runs] == [1, 0]


def test_empty_checkpoint_cursor_starts_from_beginning(store: FakeStore) -> None:
    store.checkpoints[EVENT_CP] = {
        "siem_profile": "elk-test",
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": {},
        "updated_at": 1793753940000,
    }
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})

    run_with(store, fake)

    (body,) = fake.search_bodies()
    assert body["query"] == {"exists": {"field": "@timestamp"}}


@pytest.mark.parametrize(
    "cursor",
    [
        {"time_ms": None},
        {"time_ms": True},
        {"time_ms": -1},
        {"time_ms": 1.5},
        {"time_ms": "100"},
        {"other": 100},
        [],
        None,
    ],
)
def test_invalid_checkpoint_cursor_fails_before_pit(store: FakeStore, cursor) -> None:
    store.checkpoints[EVENT_CP] = {
        "siem_profile": "elk-test",
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": cursor,
        "updated_at": 1793753940000,
    }
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})

    result = run_with(store, fake)

    assert result.failure == "checkpoint_cursor"
    assert fake.calls() == []
