"""Core SIEM entry: picks the adapter by setting, never by name in code (box 3, K3, K66)."""

import ast
from pathlib import Path

import pytest
from fake_siem import FAKE_ALERTS, FakeSiem, fake_factory

from soc.config import ConfigError, MissingSecretError, load_config
from soc.contracts import ContractValidationError, SiemAlert
from soc.ingest.connector import open_connector
from soc.ingest.siem import SIEM_CONNECTORS
from soc.ingest.siem.base import FetchBatch, HealthStatus
from soc.plugins import PluginNotFoundError, PluginRegistry

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "src" / "soc" / "ingest"
TOKEN = "fake-token-not-a-secret"
ENV = {"SIEM_TOKEN": TOKEN}


def org_settings(tmp_path, body):
    org = tmp_path / "org.toml"
    org.write_text(body, encoding="utf-8")
    return load_config(org, environ={})


def fake_registry(factory=fake_factory):
    registry = PluginRegistry("siem")
    registry.register("fake", factory)
    return registry


FAKE_CONFIG = '[siem]\nadapter = "fake"\nbase_url = "https://siem.example.com"\nbatch_size = 2\n'


def test_default_settings_pick_no_adapter_so_direct_is_never_the_default():
    settings = load_config(environ={})
    assert settings.siem.adapter == ""
    with pytest.raises(ConfigError, match="siem.adapter"):
        open_connector(settings, environ={})


def test_direct_is_registered_in_the_repo():
    assert "direct" in SIEM_CONNECTORS.names()


def test_core_runs_the_fake_siem_chosen_by_setting(tmp_path):
    connector = open_connector(
        org_settings(tmp_path, FAKE_CONFIG), environ=ENV, registry=fake_registry()
    )
    batch = connector.fetch(None)
    assert [item.model_dump(mode="json") for item in batch.items] == FAKE_ALERTS[:2]
    assert connector.health_check() == HealthStatus(
        ok=True, detail="connected to https://siem.example.com"
    )


def test_core_passes_batch_size_as_limit(tmp_path):
    created = []

    def factory(settings, environ):
        created.append(fake_factory(settings, environ))
        return created[-1]

    connector = open_connector(
        org_settings(tmp_path, FAKE_CONFIG), environ=ENV, registry=fake_registry(factory)
    )
    connector.fetch(None)
    assert created[0].limits == [2]


def test_unknown_adapter_fails_with_available_names(tmp_path):
    settings = org_settings(tmp_path, '[siem]\nadapter = "nope"\n')
    with pytest.raises(PluginNotFoundError, match="Available: fake"):
        open_connector(settings, environ=ENV, registry=fake_registry())


class NotC2Siem(FakeSiem):
    def fetch(self, cursor, limit):
        return FetchBatch(items=({"kind": "alert", "raw_ids": [], "fields": {}},), next_cursor="1")


def test_core_rejects_plugin_output_that_is_not_c2(tmp_path):
    registry = fake_registry(lambda settings, environ: NotC2Siem("x", TOKEN))
    connector = open_connector(org_settings(tmp_path, FAKE_CONFIG), environ=ENV, registry=registry)
    with pytest.raises(ContractValidationError) as error:
        connector.fetch(None)
    assert error.value.rule == "required"


class DictSiem(FakeSiem):
    def fetch(self, cursor, limit):
        return FetchBatch(items=(FAKE_ALERTS[0],), next_cursor="1")


def test_core_turns_valid_plugin_dicts_into_c2_models(tmp_path):
    registry = fake_registry(lambda settings, environ: DictSiem("x", TOKEN))
    connector = open_connector(org_settings(tmp_path, FAKE_CONFIG), environ=ENV, registry=registry)
    assert isinstance(connector.fetch(None).items[0], SiemAlert)


def test_siem_token_is_read_from_env_only(tmp_path):
    settings = org_settings(tmp_path, FAKE_CONFIG)
    with pytest.raises(MissingSecretError, match="SIEM_TOKEN"):
        open_connector(settings, environ={}, registry=fake_registry())


def test_siem_token_literal_in_settings_fails_without_echoing_it(tmp_path):
    with pytest.raises(ConfigError, match="siem.token_env") as error:
        org_settings(tmp_path, '[siem]\ntoken_env = "s3cr3t-token-value"\n')
    assert "s3cr3t" not in str(error.value)


def test_siem_token_env_is_listed_in_env_example():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"# {load_config(environ={}).siem.token_env}=" in example


def _string_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_core_has_no_siem_name_branch():
    """Only adapter modules and the registration in siem/__init__.py may name an adapter."""
    adapter_modules = {p for p in (INGEST / "siem").glob("*.py") if p.name not in {"base.py"}}
    core = [p for p in INGEST.rglob("*.py") if p not in adapter_modules]
    assert core, "no core ingest modules found"
    names = set(SIEM_CONNECTORS.names()) | {"wazuh", "elk", "elastic", "splunk"}
    for path in core:
        literals = _string_literals(path)
        source = path.read_text(encoding="utf-8").lower()
        for name in names:
            assert name not in literals, f"{path.name} names the '{name}' adapter"
            assert f"import {name}" not in source and f".{name} import" not in source
