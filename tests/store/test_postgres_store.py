"""PostgreSQL Alert/Event store (boxes 6, 7, D-002): the shared contract plus table rules.

Marked `db`: needs PostgreSQL through DATABASE_URL (`docker compose up -d`), and
runs in CI against the service container with `uv run pytest -m db`.
"""

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from store_contract import CURSOR_KEY, Clock, RecordStoreContract, dump, load_alert_records, load_c2
from test_ingest_run import direct_ingest, run_until_done, stored_sources

from soc.config import load_config
from soc.db import apply_migrations, connect
from soc.store.ingest import ingest_once
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
