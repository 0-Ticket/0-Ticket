from importlib.metadata import entry_points
from types import SimpleNamespace

from soc.l1.tickets import open_ticket_store
from soc.plugins import PluginRegistry
from soc.store.postgresql.tickets import create_postgresql_ticket_store


def test_postgresql_ticket_store_is_registered_in_the_stores_entry_point_group():
    registered = {entry.name: entry.value for entry in entry_points(group="zero_ticket_soc.stores")}

    assert registered["postgresql.tickets"] == (
        "soc.store.postgresql.tickets:create_postgresql_ticket_store"
    )
    assert PluginRegistry("stores").get("postgresql.tickets") is create_postgresql_ticket_store


def test_open_ticket_store_uses_the_common_store_registry():
    calls = []

    def create_fake_ticket_store(settings, environ):
        calls.append((settings, environ))
        return "fake-ticket-store"

    settings = SimpleNamespace(store=SimpleNamespace(backend="fake"))
    registry = PluginRegistry("stores")
    registry.register("fake.tickets", create_fake_ticket_store)

    result = open_ticket_store(settings, environ={"DATABASE_URL": "fake"}, registry=registry)

    assert result == "fake-ticket-store"
    assert calls == [(settings, {"DATABASE_URL": "fake"})]
