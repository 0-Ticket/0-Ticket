"""How the screen API opens its stores (box 27): read-only kinds, closed on shutdown."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agent_log_fakes import FakeAgentLogStore
from fake_ticket_store import FakeTicketStore

from soc.api import __main__ as api_main
from soc.api.readers import SharedTicketReader, open_readers
from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.agent_log import AgentLogService

TICKET = Path(__file__).resolve().parents[1] / "fixtures" / "api" / "l1_results.json"

READ_ONLY_KINDS = {
    "readonly_tickets",
    "readonly_records",
    "readonly_l1_decisions",
    "readonly_branches",
    "readonly_agent_log",
}


class Reader:
    """Stands in for any store open_readers opens."""

    def __init__(self, kind):
        self.kind = kind
        self.closed = False

    def close(self):
        self.closed = True


def test_open_readers_opens_read_only_kinds_only(monkeypatch):
    opened = {}

    def fake_open_store(kind, settings, environ=None, registry=None):
        opened[kind] = Reader(kind)
        return opened[kind]

    def fake_open_queue(settings, environ=None, *, readonly=False):
        opened["queue"] = Reader("queue")
        opened["queue"].readonly = readonly
        return opened["queue"]

    monkeypatch.setattr("soc.api.readers.open_store", fake_open_store)
    monkeypatch.setattr("soc.api.readers.open_evidence_queue", fake_open_queue)

    readers = open_readers(load_config(environ={}), environ={})

    assert set(opened) - {"queue"} == READ_ONLY_KINDS
    assert opened["queue"].readonly is True

    readers.close()
    assert all(reader.closed for reader in opened.values())


def test_close_is_safe_to_call_twice(monkeypatch):
    """Shutdown may follow an explicit close; the second call must not fail."""
    monkeypatch.setattr(
        "soc.api.readers.open_store",
        lambda kind, settings, environ=None, registry=None: Reader(kind),
    )
    monkeypatch.setattr(
        "soc.api.readers.open_evidence_queue",
        lambda settings, environ=None, *, readonly=False: Reader("queue"),
    )
    readers = open_readers(load_config(environ={}), environ={})
    readers.close()
    readers.close()


def test_the_agent_log_does_not_close_the_shared_ticket_store(tmp_path):
    """``list_for_ticket`` closes the store its factory returns; the API shares one."""
    data = json.loads(TICKET.read_text(encoding="utf-8"))
    tickets = FakeTicketStore()
    tickets.create(data["tickets"][0])
    store = FakeAgentLogStore()
    service = AgentLogService(
        store, tmp_path, ticket_store_factory=lambda: SharedTicketReader(tickets)
    )
    service.record(validate_contract("AgentStep", data["steps"][1]))

    assert [entry.step.subject_id for entry in service.list_for_ticket("tk_api_escalated")] == [
        "tk_api_escalated"
    ]
    assert tickets.closed is False


def test_the_command_serves_the_configured_host_and_port(monkeypatch):
    served = {}

    monkeypatch.setattr(api_main, "open_readers", lambda settings, environ: "readers")
    monkeypatch.setattr(api_main, "create_app", lambda readers: f"app-for-{readers}")
    monkeypatch.setattr(
        api_main.uvicorn,
        "run",
        lambda app, host, port: served.update(app=app, host=host, port=port),
    )

    assert api_main.main([], environ={}) == 0
    settings = load_config(environ={})
    assert served == {
        "app": "app-for-readers",
        "host": settings.api.host,
        "port": settings.api.port,
    }


def test_the_default_address_is_local_only():
    settings = load_config(environ={})
    assert (settings.api.host, settings.api.port) == ("127.0.0.1", 8000)


@pytest.mark.parametrize(
    "overrides",
    [{"host": ""}, {"port": 0}, {"port": 70000}],
)
def test_bad_api_settings_are_rejected(tmp_path, overrides):
    config = tmp_path / "org.toml"
    body = "\n".join(
        f'{key} = "{value}"' if isinstance(value, str) else f"{key} = {value}"
        for key, value in overrides.items()
    )
    config.write_text(f"[api]\n{body}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path=config, environ={})


class OneAtATimeReader(Reader):
    """Fails if two calls are inside it at once, as a shared psycopg connection would."""

    def __init__(self, kind):
        super().__init__(kind)
        self.inside = 0
        self.overlaps = 0

    def get(self, *args):
        self.inside += 1
        if self.inside > 1:
            self.overlaps += 1
        time.sleep(0.002)
        self.inside -= 1
        return None


def test_open_readers_lets_one_request_at_a_time_into_the_stores(monkeypatch):
    """#97: every store open_readers opens shares one connection, so access is serialized."""
    opened = {}

    def fake_open_store(kind, settings, environ=None, registry=None):
        opened[kind] = OneAtATimeReader(kind)
        return opened[kind]

    def fake_open_queue(settings, environ=None, *, readonly=False):
        opened["queue"] = OneAtATimeReader("queue")
        return opened["queue"]

    monkeypatch.setattr("soc.api.readers.open_store", fake_open_store)
    monkeypatch.setattr("soc.api.readers.open_evidence_queue", fake_open_queue)
    given = {}

    def agent_log_service(store, *args, **kwargs):
        given["agent_log"] = store
        return AgentLogService(store, *args, **kwargs)

    monkeypatch.setattr("soc.api.readers.AgentLogService", agent_log_service)
    readers = open_readers(load_config(environ={}), environ={})
    stores = [
        readers.tickets,
        readers.records,
        readers.decisions,
        readers.branches,
        readers.evidence_queue,
        given["agent_log"],
    ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda index: stores[index % len(stores)].get("x"), range(120)))

    assert {kind: reader.overlaps for kind, reader in opened.items()} == dict.fromkeys(opened, 0)
    readers.close()
    assert all(reader.closed for reader in opened.values())
