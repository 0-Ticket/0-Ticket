from importlib.metadata import entry_points
from types import SimpleNamespace

from soc.l1.agent_log import open_agent_log_store
from soc.plugins import PluginRegistry
from soc.store.postgresql.agent_log import create_postgresql_agent_log_store


def test_postgresql_agent_log_store_is_registered_in_the_stores_entry_point_group():
    registered = {entry.name: entry.value for entry in entry_points(group="zero_ticket_soc.stores")}

    assert registered["postgresql.agent_log"] == (
        "soc.store.postgresql.agent_log:create_postgresql_agent_log_store"
    )
    assert PluginRegistry("stores").get("postgresql.agent_log") is (
        create_postgresql_agent_log_store
    )


def test_open_agent_log_store_uses_the_common_store_registry():
    calls = []

    def create_fake_store(settings, environ):
        calls.append((settings, environ))
        return "fake-agent-log-store"

    settings = SimpleNamespace(store=SimpleNamespace(backend="fake"))
    registry = PluginRegistry("stores")
    registry.register("fake.agent_log", create_fake_store)

    result = open_agent_log_store(settings, environ={"DATABASE_URL": "fake"}, registry=registry)

    assert result == "fake-agent-log-store"
    assert calls == [(settings, {"DATABASE_URL": "fake"})]
