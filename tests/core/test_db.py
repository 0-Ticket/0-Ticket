"""PostgreSQL connection and SQL-file migrations (D-002).

Tests marked `db` need a running PostgreSQL reachable through DATABASE_URL
(`docker compose up -d`). They are excluded from the default run and run in CI
against a service container: `uv run pytest -m db`.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from soc.config import MissingSecretError, load_config
from soc.db import (
    DatabaseConnectionError,
    MigrationError,
    apply_migrations,
    connect,
    connect_readonly,
    discover_migrations,
)
from soc.db.connection import READ_ONLY_OPTIONS
from soc.db.migrator import DEFAULT_MIGRATIONS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "migrations"


def test_migration_files_ordered():
    migrations = discover_migrations(FIXTURES / "ok")
    assert [(m.version, m.name) for m in migrations] == [
        (1, "create_sample"),
        (2, "seed_sample"),
    ]


def test_duplicate_number_fails():
    with pytest.raises(MigrationError, match="0001"):
        discover_migrations(FIXTURES / "dup")


def test_badly_named_file_fails():
    with pytest.raises(MigrationError, match="create_sample.sql"):
        discover_migrations(FIXTURES / "badname")


def test_default_migrations_folder_is_valid():
    assert DEFAULT_MIGRATIONS.is_dir()
    discover_migrations(DEFAULT_MIGRATIONS)


def test_connect_without_env_fails_cleanly():
    with pytest.raises(MissingSecretError, match="DATABASE_URL"):
        connect(load_config(environ={}), environ={})


def test_invalid_url_error_hides_password():
    environ = {"DATABASE_URL": "not a url password=hunter-two-example"}
    with pytest.raises(DatabaseConnectionError) as caught:
        connect(load_config(environ={}), environ=environ)
    assert "hunter-two-example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_unreachable_server_error_hides_password():
    url = "postgresql://analyst:hunter-two-example@127.0.0.1:1/soc"
    with pytest.raises(DatabaseConnectionError) as caught:
        connect(load_config(environ={}), environ={"DATABASE_URL": url})
    assert "DATABASE_URL" in str(caught.value)
    assert "hunter-two-example" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.fixture
def connect_calls(monkeypatch):
    """Record what each connect function passes to the driver (#83)."""
    calls = []
    monkeypatch.setattr(psycopg, "connect", lambda url, **kwargs: calls.append(kwargs))
    return calls


def test_connect_opens_autocommit_connections(connect_calls):
    environ = {"DATABASE_URL": "postgresql://analyst@127.0.0.1:1/soc"}
    connect(load_config(environ={}), environ=environ)
    # A read must not leave a transaction open that later writes join and close rolls back.
    assert connect_calls[0]["autocommit"] is True
    assert "options" not in connect_calls[0]


def test_readonly_connect_keeps_read_only_option(connect_calls):
    environ = {"DATABASE_READONLY_URL": "postgresql://reader@127.0.0.1:1/soc"}
    connect_readonly(load_config(environ={}), environ=environ)
    assert connect_calls[0]["autocommit"] is True
    assert connect_calls[0]["options"] == READ_ONLY_OPTIONS


@pytest.fixture
def conn():
    """A connection whose search_path is a fresh schema, dropped afterwards."""
    with connect(load_config(environ=os.environ)) as connection:
        schema = f"zt_test_{uuid.uuid4().hex[:12]}"
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            connection.commit()


def applied_versions(connection):
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    return [row[0] for row in rows.fetchall()]


@pytest.mark.db
def test_db_connect_select_1(conn):
    assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.db
def test_migrations_apply_once(conn):
    first = apply_migrations(conn, FIXTURES / "ok")
    second = apply_migrations(conn, FIXTURES / "ok")
    assert [m.version for m in first] == [1, 2]
    assert second == []
    assert applied_versions(conn) == [1, 2]
    assert conn.execute("SELECT count(*) FROM sample_item").fetchone() == (2,)


@pytest.mark.db
def test_failed_migration_rolls_back(conn):
    with pytest.raises(MigrationError, match="0002_half_applied"):
        apply_migrations(conn, FIXTURES / "broken")
    assert applied_versions(conn) == [1]
    exists = conn.execute("SELECT to_regclass('sample_extra')").fetchone()
    assert exists == (None,)


@pytest.mark.db
def test_default_migrations_apply(conn):
    apply_migrations(conn, DEFAULT_MIGRATIONS)
    assert isinstance(conn, psycopg.Connection)
