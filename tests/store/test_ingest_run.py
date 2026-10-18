"""direct replay -> source records -> cursor, resumed on the next run (boxes 3 -> 6, 7)."""

from pathlib import Path

import pytest
from fake_store import FakeRecordStore
from store_contract import dump, load_c2

from soc.config import load_config
from soc.ingest.connector import open_connector
from soc.store.ingest import IngestRun, ingest_once

ROOT = Path(__file__).resolve().parents[2]
DIRECT_CONFIG = ROOT / "tests" / "fixtures" / "ingest" / "direct.toml"


def direct_ingest(tmp_path, monkeypatch, batch_size):
    monkeypatch.chdir(ROOT)  # The direct settings use paths from the repo root.
    org = tmp_path / "org.toml"
    org.write_text(
        DIRECT_CONFIG.read_text(encoding="utf-8").replace(
            '[siem]\nadapter = "direct"', f'[siem]\nadapter = "direct"\nbatch_size = {batch_size}'
        ),
        encoding="utf-8",
    )
    settings = load_config(org, environ={})
    return settings, open_connector(settings, environ={})


def stored_sources(store):
    return [
        dump(s.record)
        for kind in ("alert", "event")
        for s in store.list_source_records(kind, None, 100)
    ]


def run_until_done(ingest, store, cursor_key):
    runs = []
    for _ in range(10):
        runs.append(ingest_once(ingest, store, cursor_key))
        if runs[-1].fetched == 0:
            return runs
    pytest.fail("ingest never caught up")


def test_ingest_resumes_from_saved_cursor(tmp_path, monkeypatch):
    settings, ingest = direct_ingest(tmp_path, monkeypatch, batch_size=4)
    store = FakeRecordStore()
    key = settings.siem.adapter

    runs = run_until_done(ingest, store, key)

    assert [(r.fetched, r.inserted, r.duplicates) for r in runs] == [
        (4, 4, 0),
        (2, 2, 0),
        (0, 0, 0),
    ]
    assert runs[-1].next_cursor == store.load_cursor(key)
    assert sorted(stored_sources(store), key=lambda c: c["source_record_id"]) == sorted(
        (dump(item) for item in load_c2()), key=lambda c: c["source_record_id"]
    )


def test_a_new_run_with_a_lost_cursor_stores_nothing_twice(tmp_path, monkeypatch):
    settings, ingest = direct_ingest(tmp_path, monkeypatch, batch_size=10)
    store = FakeRecordStore()
    ingest_once(ingest, store, "first")
    again = ingest_once(ingest, store, "second")  # Another key starts from the beginning.
    assert again == IngestRun(
        fetched=6, inserted=0, duplicates=6, skipped=1, next_cursor=store.load_cursor("second")
    )
    assert len(stored_sources(store)) == 6
