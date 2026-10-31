"""PostgreSQL Alert/Event store (boxes 6, 7, D-002): the shared contract plus table rules.

Marked `db`: needs PostgreSQL through DATABASE_URL (`docker compose up -d`), and
runs in CI against the service container with `uv run pytest -m db`.
"""

import hashlib
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from store_contract import (
    CURSOR_KEY,
    Clock,
    RecordStoreContract,
    dump,
    failure,
    load_alert_records,
    load_c2,
)
from test_ingest_run import direct_ingest, run_until_done, stored_sources

from soc.config import load_config
from soc.db import apply_migrations, connect
from soc.store.ingest import ingest_once
from soc.store.records.base import SourceFailure
from soc.store.records.postgres import PostgresRecordStore

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    """A connection to a fresh schema with every migration applied, dropped afterwards."""
    with connect(load_config(environ=os.environ)) as connection:
        schema = f"zt_test_{uuid.uuid4().hex[:12]}"
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.commit()
        apply_migrations(connection)
        try:
            yield connection
        finally:
            connection.rollback()
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            connection.commit()


class TestPostgresRecordStoreContract(RecordStoreContract):
    @pytest.fixture
    def make_store(self, conn):
        def make(retention_days=0, clock=None):
            return PostgresRecordStore(conn, retention_days, clock or Clock())

        return make


def test_source_record_update_is_rejected(conn):
    store = PostgresRecordStore(conn, 0, Clock())
    item = load_c2()[0]
    store.save_source_records([item], CURSOR_KEY, "c1")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"), conn.transaction():
        conn.execute("UPDATE source_records SET content = '{}'::json")
    assert dump(store.get_source_record(item.source_record_id)) == dump(item)


def test_referenced_source_cannot_be_deleted(conn):
    store = PostgresRecordStore(conn, 0, Clock())
    store.save_source_records(load_c2(), CURSOR_KEY, "c1")
    store.save_alert_record(load_alert_records()[0])
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute("DELETE FROM source_records")


def test_legacy_event_record_reads_with_null_http_bytes(conn):
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "store" / "legacy_event_record.json"
    )
    legacy = json.loads(fixture.read_text(encoding="utf-8"))
    source = next(item for item in load_c2() if item.source_record_id == legacy["source_record_id"])
    store = PostgresRecordStore(conn, 0, Clock())
    store.save_source_records([source], CURSOR_KEY, "c1")

    conn.execute(
        "INSERT INTO event_records"
        " (event_id, source_record_id, time, src_ip, dst_ip, host, record)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s::json)",
        (
            legacy["event_id"],
            legacy["source_record_id"],
            legacy["time"],
            legacy["src_ip"],
            legacy["dst_ip"],
            legacy["host"],
            json.dumps(legacy),
        ),
    )

    record = store.get_event_record(legacy["event_id"])
    assert record is not None
    assert record.http_bytes is None

    found = store.find_event_records("host", legacy["host"], legacy["time"], legacy["time"] + 1, 10)
    assert len(found) == 1
    assert found[0].http_bytes is None

    persisted = conn.execute(
        "SELECT record FROM event_records WHERE event_id = %s", (legacy["event_id"],)
    ).fetchone()[0]
    if isinstance(persisted, str):
        persisted = json.loads(persisted)
    assert "http_bytes" not in persisted


def _legacy_source_id(content):
    canonical = json.dumps(
        {key: content[key] for key in ("kind", "scenario", "raw_ids", "fields")},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "src_" + hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    ("fixture_name", "kind"),
    [("legacy_siem_alert.json", "alert"), ("legacy_siem_event.json", "event")],
)
def test_legacy_source_records_read_as_mapping_profile_without_rewrite(conn, fixture_name, kind):
    legacy = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/store" / fixture_name).read_text(
            encoding="utf-8"
        )
    )
    source_id = _legacy_source_id(legacy)
    assert legacy["source_record_id"] == source_id
    conn.execute(
        "INSERT INTO source_records (source_record_id, kind, content, ingested_at)"
        " VALUES (%s, %s, %s::json, %s)",
        (source_id, kind, json.dumps(legacy), 1791849600000),
    )

    store = PostgresRecordStore(conn, 0, Clock())
    fetched = store.get_source_record(source_id)
    [listed] = store.list_source_records(kind, None, 10)
    assert fetched.kind == kind
    assert fetched.mapping_profile == "legacy_profile"
    assert listed.record.mapping_profile == "legacy_profile"
    assert fetched.source_record_id == listed.record.source_record_id == source_id
    duplicate = store.save_source_records([fetched], "legacy", None)
    assert (duplicate.inserted, duplicate.duplicates) == (0, 1)

    persisted = conn.execute(
        "SELECT content FROM source_records WHERE source_record_id = %s", (source_id,)
    ).fetchone()[0]
    if isinstance(persisted, str):
        persisted = json.loads(persisted)
    assert persisted == legacy


def test_legacy_normalize_failure_reads_as_mapping_profile_without_rewrite(conn):
    root = Path(__file__).resolve().parents[1] / "fixtures/store"
    source = json.loads((root / "legacy_siem_alert.json").read_text(encoding="utf-8"))
    failure = json.loads((root / "legacy_normalize_failure.json").read_text(encoding="utf-8"))
    source_id = _legacy_source_id(source)
    conn.execute(
        "INSERT INTO source_records (source_record_id, kind, content, ingested_at)"
        " VALUES (%s, 'alert', %s::json, %s)",
        (source_id, json.dumps(source), 1791849600000),
    )
    conn.execute(
        "INSERT INTO normalize_failures (source_record_id, source_kind, reason, failed_at, record)"
        " VALUES (%s, 'alert', %s, %s, %s::json)",
        (source_id, failure["reason"], failure["failed_at"], json.dumps(failure)),
    )

    store = PostgresRecordStore(conn, 0, Clock())
    fetched = store.get_normalize_failure(source_id)
    assert fetched.mapping_profile == "legacy_profile"
    assert fetched.reason == "unknown_scenario"
    persisted = conn.execute(
        "SELECT record FROM normalize_failures WHERE source_record_id = %s", (source_id,)
    ).fetchone()[0]
    if isinstance(persisted, str):
        persisted = json.loads(persisted)
    assert persisted == failure


def test_unknown_mapping_profile_failure_persists_after_migration(conn):
    source = next(item for item in load_c2() if item.kind == "alert")
    store = PostgresRecordStore(conn, 0, Clock())
    store.save_source_records([source], CURSOR_KEY, "c1")
    result = failure("unknown_mapping_profile", source.raw_ids)

    store.save_normalize_batch("alert", [], [SourceFailure(source.source_record_id, result)], 1)

    assert store.get_normalize_failure(source.source_record_id).reason == "unknown_mapping_profile"
    reason, record = conn.execute(
        "SELECT reason, record FROM normalize_failures WHERE source_record_id = %s",
        (source.source_record_id,),
    ).fetchone()
    if isinstance(record, str):
        record = json.loads(record)
    assert reason == "unknown_mapping_profile"
    assert record == dump(result)


@pytest.mark.parametrize("table", ["alert_records", "event_records"])
def test_entity_time_indexes_exist(conn, table):
    rows = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s",
        (table,),
    ).fetchall()
    definitions = {row[0].split(" USING btree ")[1] for row in rows if " USING btree " in row[0]}
    for columns in ('("time")', '(src_ip, "time")', '(dst_ip, "time")', '(host, "time")'):
        assert columns in definitions, f"{table} lacks index {columns}"


def test_direct_replay_is_stored_and_resumed(conn, tmp_path, monkeypatch):
    settings, ingest = direct_ingest(tmp_path, monkeypatch, batch_size=4)
    store = PostgresRecordStore(conn, 0, Clock())
    runs = run_until_done(ingest, store, settings.siem.adapter)
    assert [r.fetched for r in runs] == [4, 2, 0]

    # A new store on the same database picks up where the last one stopped.
    again = ingest_once(ingest, PostgresRecordStore(conn, 0, Clock()), settings.siem.adapter)
    assert again.fetched == 0
    assert sorted(stored_sources(store), key=lambda c: c["source_record_id"]) == sorted(
        (dump(item) for item in load_c2()), key=lambda c: c["source_record_id"]
    )


@pytest.mark.parametrize("table", ["alert_records", "event_records"])
def test_one_normalized_result_per_source(conn, table):
    rows = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s",
        (table,),
    ).fetchall()
    assert any(
        row[0].startswith("CREATE UNIQUE INDEX") and row[0].endswith("(source_record_id)")
        for row in rows
    )
