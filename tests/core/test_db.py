"""PostgreSQL connection and SQL-file migrations (D-002).

Tests marked `db` need a running PostgreSQL reachable through DATABASE_URL
(`docker compose up -d`). They are excluded from the default run and run in CI
against a service container: `uv run pytest -m db`.
"""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import PoolTimeout

import soc.db.connection
from soc.config import MissingSecretError, load_config
from soc.db import (
    DatabaseConnectionError,
    MigrationError,
    apply_migrations,
    connect,
    connect_readonly,
    discover_migrations,
    open_readonly_pool,
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


# Read-only connection pool for the screen API (#104)


@pytest.fixture
def pool_calls(monkeypatch):
    """Record what ``open_readonly_pool`` passes to psycopg_pool (#104)."""
    calls = []

    class FakeConnectionPool:
        def __init__(self, conninfo, **kwargs):
            calls.append({"conninfo": conninfo, **kwargs})

        def open(self, wait=False, timeout=30.0):
            calls.append({"open": {"wait": wait, "timeout": timeout}})

        def close(self):
            calls.append({"close": True})

    monkeypatch.setattr(soc.db.connection, "ConnectionPool", FakeConnectionPool)
    return calls


def test_readonly_pool_keeps_the_read_only_connection_options(pool_calls):
    """The pool opens its own connections, so #83's autocommit and the read-only
    transaction option have to travel with it (docs/security-policy.md 4)."""
    environ = {"DATABASE_READONLY_URL": "postgresql://reader@127.0.0.1:1/soc"}
    open_readonly_pool(load_config(environ={}), environ=environ)
    created = pool_calls[0]
    assert created["kwargs"] == {
        "autocommit": True,
        "options": READ_ONLY_OPTIONS,
        "connect_timeout": 5,
    }
    # Idle connections are pointless for a read-only screen API; the pool grows on demand.
    assert created["min_size"] == 1
    assert created["max_size"] == 8
    assert created["timeout"] == 5
    # The service opens the pool in its lifespan, not in the constructor.
    assert created["open"] is False


def test_readonly_pool_without_env_fails_cleanly(pool_calls):
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        open_readonly_pool(load_config(environ={}), environ={})


def test_readonly_pool_invalid_url_error_hides_password(pool_calls):
    environ = {"DATABASE_READONLY_URL": "not a url password=hunter-two-example"}
    with pytest.raises(DatabaseConnectionError) as caught:
        open_readonly_pool(load_config(environ={}), environ=environ)
    assert "hunter-two-example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_pool_start_failure_hides_url_and_password(monkeypatch):
    """A pool that cannot fill must not put the URL in the message it fails with."""
    url = "postgresql://reader:hunter-two-example@127.0.0.1:1/soc"

    class FailingPool:
        def __init__(self, conninfo, **kwargs):
            pass

        def open(self, wait=False, timeout=30.0):
            raise PoolTimeout(f"pool initialization incomplete, {url} is unreachable")

    monkeypatch.setattr(soc.db.connection, "ConnectionPool", FailingPool)
    pool = open_readonly_pool(load_config(environ={}), environ={"DATABASE_READONLY_URL": url})
    with pytest.raises(DatabaseConnectionError) as caught:
        pool.open()
    assert "DATABASE_READONLY_URL" in str(caught.value)
    assert "hunter-two-example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_pool_start_waits_so_a_broken_database_fails_the_service(pool_calls):
    """``wait=False`` connects in the background, so a start failure would pass unnoticed."""
    environ = {"DATABASE_READONLY_URL": "postgresql://reader@127.0.0.1:1/soc"}
    open_readonly_pool(load_config(environ={}), environ=environ).open()
    assert pool_calls[1] == {"open": {"wait": True, "timeout": 5}}


def test_pool_borrow_failure_hides_url_and_password(monkeypatch):
    url = "postgresql://reader:hunter-two-example@127.0.0.1:1/soc"

    class ExhaustedPool:
        def __init__(self, conninfo, **kwargs):
            pass

        @contextmanager
        def connection(self, timeout=None):
            raise PoolTimeout(f"no connection left for {url}")
            yield  # pragma: no cover

    monkeypatch.setattr(soc.db.connection, "ConnectionPool", ExhaustedPool)
    pool = open_readonly_pool(load_config(environ={}), environ={"DATABASE_READONLY_URL": url})
    with pytest.raises(DatabaseConnectionError) as caught:
        with pool.connection():
            pass  # pragma: no cover
    assert "DATABASE_READONLY_URL" in str(caught.value)
    assert "hunter-two-example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_error_during_the_request_is_not_reported_as_a_borrow_failure(monkeypatch):
    """Pool exceptions subclass psycopg.OperationalError, so only the borrow itself
    is converted: an error raised while the request reads must stay what it is."""
    returned = []

    class LendingPool:
        def __init__(self, conninfo, **kwargs):
            pass

        @contextmanager
        def connection(self, timeout=None):
            try:
                yield "connection"
            finally:
                returned.append(True)

    monkeypatch.setattr(soc.db.connection, "ConnectionPool", LendingPool)
    url = "postgresql://reader@127.0.0.1:1/soc"
    pool = open_readonly_pool(load_config(environ={}), environ={"DATABASE_READONLY_URL": url})
    with pytest.raises(psycopg.OperationalError) as caught:
        with pool.connection() as conn:
            assert conn == "connection"
            raise psycopg.OperationalError("the server closed the connection")
    assert not isinstance(caught.value, DatabaseConnectionError)
    # The connection goes back even when the request fails.
    assert returned == [True]
