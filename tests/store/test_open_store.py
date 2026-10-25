"""Stores are found by "<backend>.<kind>" from [store] backend, never by name in code."""

import ast
from pathlib import Path

import pytest
from fake_branch_store import FakeBranchStore, fake_branches_factory
from fake_l1_decision_store import FakeL1DecisionStore, fake_l1_decisions_factory
from fake_store import FakeRecordStore, fake_records_factory

from soc.config import ConfigError, MissingSecretError, load_config
from soc.plugins import PluginNotFoundError, PluginRegistry
from soc.store import STORES, open_store

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "src" / "soc" / "store"


def org_settings(tmp_path, body):
    org = tmp_path / "org.toml"
    org.write_text(body, encoding="utf-8")
    return load_config(org, environ={})


def fake_registry():
    registry = PluginRegistry("stores")
    registry.register("fake.records", fake_records_factory)
    return registry


def test_default_settings_pick_postgresql_and_keep_sources_forever():
    settings = load_config(environ={})
    assert settings.store.backend == "postgresql"
    assert settings.store.raw_retention_days == 0


def test_postgresql_records_is_registered_in_the_repo():
    assert "postgresql.records" in STORES.names()


def test_fake_store_replaces_postgresql_by_setting(tmp_path):
    settings = org_settings(tmp_path, '[store]\nbackend = "fake"\nraw_retention_days = 7\n')
    store = open_store("records", settings, environ={}, registry=fake_registry())
    assert isinstance(store, FakeRecordStore)
    assert store.retention_days == 7


def test_unknown_backend_fails_with_available_names(tmp_path):
    settings = org_settings(tmp_path, '[store]\nbackend = "nope"\n')
    with pytest.raises(PluginNotFoundError, match="nope.records.*Available: fake.records"):
        open_store("records", settings, environ={}, registry=fake_registry())


@pytest.mark.parametrize(
    "body",
    [
        '[store]\nbackend = ""\n',
        '[store]\nbackend = "a.b"\n',
        "[store]\nraw_retention_days = -1\n",
    ],
)
def test_bad_store_settings_fail(tmp_path, body):
    with pytest.raises(ConfigError, match="store"):
        org_settings(tmp_path, body)


def test_core_store_code_has_no_backend_name_branch():
    """Only the registration and the implementation itself may name a backend."""
    allowed = {
        STORE / "__init__.py",
        STORE / "records" / "postgres.py",
        STORE / "branches" / "postgres.py",
        STORE / "l1_decisions" / "postgres.py",
        STORE / "lookups" / "postgres.py",
        STORE / "postgresql" / "tickets.py",
        STORE / "postgresql" / "agent_log.py",
    }
    for path in STORE.rglob("*.py"):
        if path in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "postgresql" not in node.value.lower(), f"{path.name} names a backend"


L1_RECORD_KINDS = (
    "branches",
    "readonly_branches",
    "l1_decisions",
    "readonly_l1_decisions",
    "readonly_tickets",
)


@pytest.mark.parametrize("kind", L1_RECORD_KINDS)
def test_l1_record_stores_are_registered_in_the_repo(kind):
    assert f"postgresql.{kind}" in STORES.names()


@pytest.mark.parametrize(
    ("kind", "factory", "expected"),
    [
        ("branches", fake_branches_factory, FakeBranchStore),
        ("l1_decisions", fake_l1_decisions_factory, FakeL1DecisionStore),
    ],
)
def test_fake_l1_record_store_replaces_postgresql_by_setting(tmp_path, kind, factory, expected):
    registry = PluginRegistry("stores")
    registry.register(f"fake.{kind}", factory)
    settings = org_settings(tmp_path, '[store]\nbackend = "fake"\n')
    assert isinstance(open_store(kind, settings, environ={}, registry=registry), expected)


@pytest.mark.parametrize("kind", [k for k in L1_RECORD_KINDS if k.startswith("readonly_")])
def test_readonly_l1_record_stores_refuse_to_use_the_writable_url(kind):
    settings = load_config(environ={})
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        open_store(kind, settings, environ={"DATABASE_URL": "postgresql://localhost/zt"})


# Borrowing a connection instead of opening one (#104, box 27)


class StubConnection:
    """Stands in for a connection the caller borrowed from a pool."""

    def __init__(self):
        self.closes = 0

    def close(self):
        self.closes += 1


def test_a_factory_that_takes_no_connection_is_called_as_before(tmp_path):
    """Without a borrowed connection the core must not pass the argument at all,
    or a backend that does not know it would fail (docs/extensibility.md)."""
    settings = org_settings(tmp_path, '[store]\nbackend = "fake"\nraw_retention_days = 7\n')
    registry = PluginRegistry("stores")
    registry.register("fake.records", fake_records_factory)
    store = open_store("records", settings, environ={}, registry=registry)
    assert isinstance(store, FakeRecordStore)


def test_open_store_hands_a_borrowed_connection_to_the_factory(tmp_path):
    settings = org_settings(tmp_path, '[store]\nbackend = "fake"\n')
    given = {}

    def factory(s, e, connection=None):
        given["connection"] = connection
        return FakeBranchStore()

    registry = PluginRegistry("stores")
    registry.register("fake.branches", factory)
    conn = StubConnection()
    open_store("branches", settings, environ={}, registry=registry, connection=conn)
    assert given["connection"] is conn


def postgres_stores(conn):
    """Every PostgreSQL store built on a connection it was handed."""
    from soc.l1.evidence.postgresql import PostgresEvidenceQueue
    from soc.store.branches.postgres import PostgresBranchStore
    from soc.store.l1_decisions.postgres import PostgresL1DecisionStore
    from soc.store.postgresql.agent_log import PostgresAgentLogStore
    from soc.store.postgresql.tickets import PostgresTicketStore
    from soc.store.records.postgres import PostgresRecordStore

    return [
        PostgresRecordStore(conn, 0),
        PostgresBranchStore(conn),
        PostgresL1DecisionStore(conn),
        PostgresTicketStore(conn),
        PostgresAgentLogStore(conn),
        PostgresEvidenceQueue(conn),
    ]


def test_a_store_does_not_close_a_connection_it_was_handed():
    """The screen API gives every store the one connection it borrowed for the
    request and gives it back itself, so no store may close it (#104)."""
    conn = StubConnection()
    for store in postgres_stores(conn):
        store.close()
    assert conn.closes == 0


READONLY_KINDS = (
    "readonly_records",
    "readonly_branches",
    "readonly_l1_decisions",
    "readonly_tickets",
    "readonly_agent_log",
)


@pytest.mark.parametrize("kind", READONLY_KINDS)
def test_every_read_only_factory_of_this_repo_takes_a_borrowed_connection(kind):
    """The screen API opens these with a connection it borrowed, so the factory
    must use it instead of connecting: with no URL in the environment it would
    otherwise fail (#104)."""
    conn = StubConnection()
    store = open_store(kind, load_config(environ={}), environ={}, connection=conn)
    store.close()
    assert conn.closes == 0


def test_the_read_only_evidence_queue_takes_a_borrowed_connection():
    from soc.l1.evidence import open_evidence_queue

    conn = StubConnection()
    queue = open_evidence_queue(load_config(environ={}), environ={}, readonly=True, connection=conn)
    queue.close()
    assert conn.closes == 0
