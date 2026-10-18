import sys
from importlib.metadata import entry_points
from types import ModuleType

from soc.l1.tickets import open_ticket_store
from soc.plugins import PluginRegistry
from soc.store.postgresql.tickets import create_postgresql_ticket_store


def test_postgresql_ticket_store_is_registered_in_the_stores_entry_point_group():
    registered = {entry.name: entry.value for entry in entry_points(group="zero_ticket_soc.stores")}

    assert registered["postgresql.tickets"] == (
        "soc.store.postgresql.tickets:create_postgresql_ticket_store"
    )
    assert PluginRegistry("stores").get("postgresql.tickets") is create_postgresql_ticket_store


def test_open_ticket_store_delegates_to_common_open_store(monkeypatch):
    calls = []
    common_store = ModuleType("soc.store")

    def open_store(kind, *args, **kwargs):
        calls.append((kind, args, kwargs))
        return "fake-ticket-store"

    common_store.open_store = open_store
    monkeypatch.setitem(sys.modules, "soc.store", common_store)
    settings = object()
    registry = PluginRegistry("stores")

    result = open_ticket_store(settings, environ={"DATABASE_URL": "fake"}, registry=registry)

    assert result == "fake-ticket-store"
    assert calls == [
        (
            "tickets",
            (settings,),
            {"environ": {"DATABASE_URL": "fake"}, "registry": registry},
        )
    ]
