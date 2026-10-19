"""Stores are found by "<backend>.<kind>" from [store] backend, never by name in code."""

import ast
from pathlib import Path

import pytest
from fake_store import FakeRecordStore, fake_records_factory

from soc.config import ConfigError, load_config
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
