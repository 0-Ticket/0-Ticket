"""How the screen API gets its stores (L1 result read): a read-only connection per request.

Before #104 every store held one connection for the whole process and a lock let
one request at a time into them. Now the API borrows one connection per request
from a pool and hands it to every store of that request.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agent_log_fakes import FakeAgentLogStore
from fake_ticket_store import FakeTicketStore

from soc.api import __main__ as api_main
from soc.api.readers import SharedTicketReader, open_reader_pool
from soc.config import load_config
from soc.contracts import validate_contract
from soc.db import DatabaseConnectionError
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
    """Stands in for any store the API opens on a borrowed connection."""

    # Set by the concurrency test: a read waits here for the other request's read.
    barrier = None

    def __init__(self, kind, connection=None):
        self.kind = kind
        self.connection = connection
        self.closed = False

    def get(self, *args):
        if type(self).barrier is not None:
            # Raises BrokenBarrierError unless another request is reading right now.
            type(self).barrier.wait()
        return None

    def close(self):
        self.closed = True


class FakePool:
    """Lends numbered connections and records what comes back."""

    def __init__(self, on_borrow=None):
        self.lent = []
        self.returned = []
        self.opened = 0
        self.closed = 0
        self.on_borrow = on_borrow

    def open(self):
        self.opened += 1

    def close(self):
        self.closed += 1

    def connection(self):
        return _Borrowed(self)


class _Borrowed:
    """What ``ReadonlyPool.connection()`` gives out: one connection, given back."""

    def __init__(self, pool):
        self._pool = pool
        self._conn = None

    def __enter__(self):
        if self._pool.on_borrow is not None:
            self._pool.on_borrow()
        self._conn = f"connection-{len(self._pool.lent)}"
        self._pool.lent.append(self._conn)
        return self._conn

    def __exit__(self, *exc):
        self._pool.returned.append(self._conn)
        return False


@pytest.fixture
def opened(monkeypatch):
    """Record every store the API opens, with the connection it was handed."""
    records = []

    def fake_open_store(kind, settings, environ=None, registry=None, connection=None):
        records.append(Reader(kind, connection))
        return records[-1]

    def fake_open_queue(settings, environ=None, *, readonly=False, connection=None):
        reader = Reader("queue", connection)
        reader.readonly = readonly
        records.append(reader)
        return reader

    monkeypatch.setattr("soc.api.readers.open_store", fake_open_store)
    monkeypatch.setattr("soc.api.readers.open_evidence_queue", fake_open_queue)
    return records


def reader_pool(pool, monkeypatch):
    monkeypatch.setattr("soc.api.readers.open_readonly_pool", lambda settings, environ: pool)
    return open_reader_pool(load_config(environ={}), environ={})


def test_the_api_opens_read_only_kinds_only(opened, monkeypatch):
    """The API never writes, so it reads through the read-only account only
    (docs/security-policy.md 4)."""
    pool = reader_pool(FakePool(), monkeypatch)
    with pool.readers():
        pass
    assert {reader.kind for reader in opened} - {"queue"} == READ_ONLY_KINDS
    assert [reader.readonly for reader in opened if reader.kind == "queue"] == [True]


def test_one_request_shares_one_connection_across_its_stores(opened, monkeypatch):
    pool = reader_pool(FakePool(), monkeypatch)
    with pool.readers():
        pass
    assert len(opened) == 6
    assert {reader.connection for reader in opened} == {"connection-0"}


def test_each_request_borrows_and_returns_its_own_connection(opened, monkeypatch):
    fake = FakePool()
    pool = reader_pool(fake, monkeypatch)
    for _ in range(3):
        with pool.readers():
            pass
    assert fake.lent == ["connection-0", "connection-1", "connection-2"]
    assert fake.returned == fake.lent


def test_the_connection_returns_after_an_exception(opened, monkeypatch):
    fake = FakePool()
    pool = reader_pool(fake, monkeypatch)
    with pytest.raises(ValueError):
        with pool.readers():
            raise ValueError("the request failed")
    assert fake.returned == ["connection-0"]


def test_the_connection_returns_when_the_request_is_cancelled(opened, monkeypatch):
    """A cancelled request ends by closing the generator the dependency waits in."""
    fake = FakePool()
    pool = reader_pool(fake, monkeypatch)
    borrowed = pool.readers()
    borrowed.__enter__()
    borrowed.gen.close()
    assert fake.returned == ["connection-0"]


def test_the_pool_opens_and_closes_with_the_service(opened, monkeypatch):
    fake = FakePool()
    pool = reader_pool(fake, monkeypatch)
    pool.open()
    pool.close()
    assert (fake.opened, fake.closed) == (1, 1)


def test_concurrent_requests_are_not_serialized(opened, monkeypatch):
    """#104: requests used to queue behind one reader lock. Each has its own
    connection now, so two of them may be inside the stores at the same time.

    The barrier sits inside the store call, so the test only passes if two reads
    are in the stores together: under the lock the second one never got in.
    """
    monkeypatch.setattr(Reader, "barrier", threading.Barrier(2, timeout=5))
    fake = FakePool()
    pool = reader_pool(fake, monkeypatch)

    def request(_):
        with pool.readers() as readers:
            readers.tickets.get("tk_x")

    with ThreadPoolExecutor(max_workers=2) as threads:
        list(threads.map(request, range(2)))

    assert len(fake.returned) == 2


def test_a_pool_failure_stays_a_connection_error(opened, monkeypatch):
    """Borrowing is where an unreachable database shows up now, and the pool has
    already taken the URL out of the message (docs/security-policy.md 2)."""

    def refuse():
        raise DatabaseConnectionError("Could not connect using DATABASE_READONLY_URL: refused")

    pool = reader_pool(FakePool(on_borrow=refuse), monkeypatch)
    with pytest.raises(DatabaseConnectionError) as caught:
        with pool.readers():
            pass  # pragma: no cover
    assert "DATABASE_READONLY_URL" in str(caught.value)


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

    monkeypatch.setattr(api_main, "open_reader_pool", lambda settings, environ: "pool")
    monkeypatch.setattr(api_main, "create_app", lambda pool: f"app-for-{pool}")
    monkeypatch.setattr(
        api_main.uvicorn,
        "run",
        lambda app, host, port: served.update(app=app, host=host, port=port),
    )

    assert api_main.main([], environ={}) == 0
    settings = load_config(environ={})
    assert served == {
        "app": "app-for-pool",
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
