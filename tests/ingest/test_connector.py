"""Core SIEM entry: picks the adapter by setting, never by name in code (box 3, K3, K66)."""

import ast
from pathlib import Path

import pytest
from fake_siem import FAKE_ALERTS, FakeSiem, fake_factory

from soc.config import ConfigError, MissingSecretError, load_config
from soc.contracts import ContractValidationError, SiemAlert
from soc.ingest.connector import canonical_c2_content, open_connector, source_record_id
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
    assert [item.model_dump(mode="json") for item in batch.items] == [
        {**alert, "source_record_id": source_record_id(alert)} for alert in FAKE_ALERTS[:2]
    ]
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


class ItemsSiem(FakeSiem):
    """Returns the given items as they are, to probe the core's checks."""

    def __init__(self, items):
        super().__init__("https://siem.example.com", TOKEN)
        self._items = tuple(items)

    def fetch(self, cursor, limit):
        return FetchBatch(items=self._items, next_cursor="1")


def fetch_items(tmp_path, *items):
    registry = fake_registry(lambda settings, environ: ItemsSiem(items))
    connector = open_connector(org_settings(tmp_path, FAKE_CONFIG), environ=ENV, registry=registry)
    return connector.fetch(None)


def test_core_rejects_plugin_output_that_is_not_c2(tmp_path):
    with pytest.raises(ContractValidationError) as error:
        fetch_items(tmp_path, {"kind": "alert", "raw_ids": [], "fields": {}})
    assert error.value.rule == "required"


def test_core_rejects_source_record_id_from_an_adapter(tmp_path):
    item = {**FAKE_ALERTS[0], "source_record_id": "src_" + "0" * 64}
    with pytest.raises(ContractValidationError) as error:
        fetch_items(tmp_path, item)
    assert (error.value.path, error.value.rule) == ("/source_record_id", "assigned_by_core")


def test_core_rejects_items_that_are_not_objects(tmp_path):
    with pytest.raises(ContractValidationError) as error:
        fetch_items(tmp_path, ["alert"])
    assert error.value.rule == "object_type"


def test_core_rejects_values_that_are_not_plain_json(tmp_path):
    item = {**FAKE_ALERTS[0], "fields": {"score": float("nan")}}
    with pytest.raises(ContractValidationError) as error:
        fetch_items(tmp_path, item)
    assert error.value.path == "/fields"


def test_core_turns_valid_plugin_dicts_into_c2_models(tmp_path):
    [item] = fetch_items(tmp_path, FAKE_ALERTS[0]).items
    assert isinstance(item, SiemAlert)
    assert item.source_record_id == source_record_id(FAKE_ALERTS[0])


PINNED_CONTENT = {
    "scenario": "s",
    "raw_ids": ["raw_1"],
    "kind": "alert",
    "fields": {"b": [1, 2], "a": "\u00e9"},
}
PINNED_BYTES = (
    b'{"fields":{"a":"\xc3\xa9","b":[1,2]},"kind":"alert","raw_ids":["raw_1"],"scenario":"s"}'
)
PINNED_ID = "src_27daf556801141c674e59006d84cd62d23f00e408f2bc9ed79c9e452a43f3b41"


def test_canonical_c2_content_is_fixed():
    """Sorted keys, no spaces, raw UTF-8. Changing this changes every stored ID."""
    assert canonical_c2_content(PINNED_CONTENT) == PINNED_BYTES
    assert source_record_id(PINNED_CONTENT) == PINNED_ID


def test_source_record_id_ignores_keys_outside_c2_content():
    assert source_record_id({**PINNED_CONTENT, "extra": 1}) == PINNED_ID


@pytest.mark.parametrize(
    "change",
    [
        {"raw_ids": ["raw_2"]},
        {"fields": {"b": [1, 2], "a": "e"}},
        {"kind": "event"},
        {"scenario": "t"},
    ],
)
def test_any_content_change_gives_a_different_id(change):
    assert source_record_id({**PINNED_CONTENT, **change}) != PINNED_ID


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
