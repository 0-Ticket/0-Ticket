"""The stores the screen API reads through (box 27, D-027).

The API never writes, so every store is opened through the read-only account
``[database] readonly_url_env`` names (``docs/security-policy.md`` 4). The core
names only store kinds, never a backend: ``[store] backend`` and
``[evidence_queue] backend`` choose the implementations (``docs/extensibility.md``).
"""

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from soc.config import Settings
from soc.l1.agent_log import AgentLogService
from soc.l1.evidence import open_evidence_queue
from soc.l1.tickets import TicketStore
from soc.plugins import PluginRegistry
from soc.store import READONLY_AGENT_LOG, READONLY_TICKETS, open_store
from soc.store.branches.base import READONLY_STORE_KIND as READONLY_BRANCHES
from soc.store.l1_decisions.base import READONLY_STORE_KIND as READONLY_L1_DECISIONS
from soc.store.records.base import READONLY_STORE_KIND as READONLY_RECORDS


class Closeable(Protocol):
    def close(self) -> None: ...


@dataclass
class ApiReaders:
    """One read-only reader per store the screen API serves from.

    ``close`` releases every connection; the app calls it when it shuts down.
    """

    tickets: Any
    records: Any
    decisions: Any
    branches: Any
    evidence_queue: Any
    agent_log: AgentLogService
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors = []
        for reader in (
            self.tickets,
            self.records,
            self.decisions,
            self.branches,
            self.evidence_queue,
            self.agent_log,
        ):
            try:
                reader.close()
            except Exception as error:  # one broken connection must not keep the rest open
                errors.append(error)
        if errors:
            raise errors[0]


@dataclass(frozen=True)
class SharedTicketReader:
    """A Ticket reader that ``AgentLogService`` may not close.

    ``AgentLogService.list_for_ticket`` closes the store its factory returns.
    The API holds one read-only Ticket store for every request, so the factory
    hands out this wrapper instead.
    """

    store: TicketStore

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        return self.store.get(ticket_id)


class LockedReader:
    """A store whose every method call holds the API's one reader lock (#97).

    Each store keeps one connection for every request, and FastAPI runs requests
    in worker threads. Two requests in the same psycopg connection nest their
    transactions and fail, so the API lets one store call in at a time. The lock is
    reentrant: the Agent Log service reads the Ticket store inside its own call.
    A connection pool (psycopg_pool) would replace this after the presentation.
    """

    def __init__(self, store: Any, lock: threading.RLock) -> None:
        self._store = store
        self._lock = lock

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._store, name)
        if not callable(value):
            return value

        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return value(*args, **kwargs)

        return locked


def open_readers(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> ApiReaders:
    """Open every read-only store the API needs, with the configured backends."""
    environ = os.environ if environ is None else environ

    lock = threading.RLock()

    def store(kind: str):
        return LockedReader(open_store(kind, settings, environ, registry=registry), lock)

    tickets = store(READONLY_TICKETS)
    agent_log = AgentLogService(
        store(READONLY_AGENT_LOG),
        settings.agent_log.artifact_dir,
        ticket_store_factory=lambda: SharedTicketReader(tickets),
    )
    return ApiReaders(
        tickets=tickets,
        records=store(READONLY_RECORDS),
        decisions=store(READONLY_L1_DECISIONS),
        branches=store(READONLY_BRANCHES),
        evidence_queue=LockedReader(open_evidence_queue(settings, environ, readonly=True), lock),
        agent_log=agent_log,
    )
