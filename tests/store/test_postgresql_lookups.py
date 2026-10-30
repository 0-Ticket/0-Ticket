"""PostgreSQL Lookup store (box 7, D-002, K7): the shared contract plus table rules.

Marked `db`: needs PostgreSQL through DATABASE_URL, and runs in CI with `uv run pytest -m db`.
"""

import os
import uuid

import pytest
from lookup_store_contract import LookupStoreContract, asset
from psycopg import sql

from soc.config import load_config
from soc.db import apply_migrations, connect
from soc.store import open_store
from soc.store.lookups.postgres import PostgresLookupStore

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


class TestPostgresLookupStoreContract(LookupStoreContract):
    @pytest.fixture
    def make_store(self, conn):
        return lambda: PostgresLookupStore(conn)


def test_lookups_are_stored_in_postgresql_tables(conn):
    store = PostgresLookupStore(conn)
    store.replace_assets([asset("192.0.2.80", "web-01", 5)])
    with conn.transaction():
        (count,) = conn.execute("SELECT count(*) FROM lookup_assets").fetchone()
    assert count == 1


def test_table_rejects_criticality_outside_one_to_five(conn):
    with pytest.raises(Exception, match="criticality"), conn.transaction():
        conn.execute(
            "INSERT INTO lookup_assets (match, network, hostname, criticality, shared, extensions)"
            " VALUES ('192.0.2.80', '192.0.2.80', 'web-01', 6, false, '{}')"
        )


def test_open_store_returns_the_postgresql_lookup_store():
    store = open_store("lookups", load_config(environ=os.environ))
    try:
        assert isinstance(store, PostgresLookupStore)
    finally:
        store.close()
