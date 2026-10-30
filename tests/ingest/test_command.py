"""The ingest command validates configured mapping selectors before opening the store."""

import pytest

import soc.ingest.__main__ as ingest_command
from soc.config import ConfigError
from soc.ingest.siem.base import FetchBatch, HealthStatus
from soc.normalize.alias import MappingSelection
from soc.plugins import PluginRegistry


def test_bad_mapping_selector_precedes_factory_store_and_fetch(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text('[siem]\nadapter = "fake"\n', encoding="utf-8")
    calls = []

    class Connector:
        def fetch(self, cursor, limit):
            calls.append("fetch")
            return FetchBatch(items=(), next_cursor=cursor)

        def health_check(self):
            return HealthStatus(ok=True, detail="available")

    class Factory:
        def mapping_selections(self, settings):
            calls.append("metadata")
            return (MappingSelection("alert", "unsupported_tool", "alerts"),)

        def __call__(self, settings, environ):
            calls.append("factory")
            return Connector()

    stores_opened = []
    monkeypatch.setattr(
        ingest_command, "open_store", lambda *args, **kwargs: stores_opened.append(1)
    )
    registry = PluginRegistry("siem")
    registry.register("fake", Factory())

    with pytest.raises(ConfigError, match="no mapping profile"):
        ingest_command.main(
            argv=[],
            environ={"ZT_CONFIG": str(settings_file)},
            siem=registry,
        )

    assert calls == ["metadata"]
    assert stores_opened == []
