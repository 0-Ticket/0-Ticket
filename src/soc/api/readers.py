"""The stores the screen API reads through (L1 result read, D-027).

The API never writes, so every store is opened through the read-only account
``[database] readonly_url_env`` names (``docs/security-policy.md`` 4). The core
names only store kinds, never a backend: ``[store] backend`` and
``[evidence_queue] backend`` choose the implementations (``docs/extensibility.md``).

Each request borrows one connection from a pool and every store of that request
reads through it, so requests no longer share a connection and their
transactions stay apart (#104).
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from soc.config import Settings
from soc.db import ReadonlyPool, open_readonly_pool
from soc.l1.agent_log import AgentLogService
from soc.l1.evidence import open_evidence_queue
from soc.l1.tickets import TicketStore
from soc.plugins import PluginRegistry
from soc.store import READONLY_AGENT_LOG, READONLY_TICKETS, open_store
from soc.store.branches.base import READONLY_STORE_KIND as READONLY_BRANCHES
from soc.store.l1_decisions.base import READONLY_STORE_KIND as READONLY_L1_DECISIONS
from soc.store.records.base import READONLY_STORE_KIND as READONLY_RECORDS


@dataclass
class ApiReaders:
    """One read-only reader per store, all on the connection of one request.

    The readers live as long as the request does; the connection goes back to
    the pool when it ends, and no reader closes it.
    """

    tickets: Any
    records: Any
    decisions: Any
    branches: Any
    evidence_queue: Any
    agent_log: AgentLogService


@dataclass(frozen=True)
class SharedTicketReader:
    """A Ticket reader that ``AgentLogService`` may not close.

    ``AgentLogService.list_for_ticket`` closes the store its factory returns.
    The request's Ticket store reads through the borrowed connection, so the
    factory hands out this wrapper instead.
    """

    store: TicketStore

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        return self.store.get(ticket_id)


class ApiReaderPool:
    """The read-only connections the screen API serves its requests from (#104).

    ``open`` and ``close`` belong to the service's start and shutdown;
    ``readers`` belongs to one request.
    """

    def __init__(
        self,
        pool: ReadonlyPool,
        settings: Settings,
        environ: Mapping[str, str],
        registry: PluginRegistry | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._environ = environ
        self._registry = registry

    def open(self) -> None:
        """Fill the pool. Raises DatabaseConnectionError if the database is unreachable."""
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def readers(self) -> Iterator[ApiReaders]:
        """Borrow a connection, open this request's readers on it, give it back."""
        with self._pool.connection() as conn:
            yield self._readers(conn)

    def _readers(self, conn: object) -> ApiReaders:
        def store(kind: str):
            return open_store(
                kind, self._settings, self._environ, registry=self._registry, connection=conn
            )

        tickets = store(READONLY_TICKETS)
        return ApiReaders(
            tickets=tickets,
            records=store(READONLY_RECORDS),
            decisions=store(READONLY_L1_DECISIONS),
            branches=store(READONLY_BRANCHES),
            evidence_queue=open_evidence_queue(
                self._settings, self._environ, readonly=True, connection=conn
            ),
            agent_log=AgentLogService(
                store(READONLY_AGENT_LOG),
                self._settings.agent_log.artifact_dir,
                ticket_store_factory=lambda: SharedTicketReader(tickets),
            ),
        )


def open_reader_pool(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> ApiReaderPool:
    """The pool the API serves from, with the configured backends. Not open yet."""
    environ = os.environ if environ is None else environ
    return ApiReaderPool(open_readonly_pool(settings, environ), settings, environ, registry)
