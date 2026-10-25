"""Stores (boxes 5, 6, 7, 10, 11, 12, 25, 27, D-002): one ``stores`` registry for every kind.

Implementations are registered as ``<backend>.<kind>``: ``postgresql.records``
for Alert/Event (boxes 6, 7), ``postgresql.readonly_records`` (the same records through
the read-only account agent tools use, box 15), ``postgresql.lookups`` (box 5),
``postgresql.branches`` (C21, box 25), ``postgresql.l1_decisions`` (C23, boxes 11, 27),
``postgresql.tickets``, and ``postgresql.agent_log``. ``readonly_branches``,
``readonly_l1_decisions``, ``readonly_tickets`` and ``readonly_agent_log`` read the
same tables through the read-only account, for the screen API (box 27).
``[store] backend`` picks the backend for all of them; the core passes only the
kind to ``open_store`` and never names a backend.
"""

import os
from collections.abc import Mapping

from soc.config import Settings
from soc.plugins import PluginRegistry

from .branches.base import READONLY_STORE_KIND as READONLY_BRANCHES
from .branches.base import STORE_KIND as BRANCHES
from .branches.postgres import create_postgres_branches, create_postgres_readonly_branches
from .l1_decisions.base import READONLY_STORE_KIND as READONLY_L1_DECISIONS
from .l1_decisions.base import STORE_KIND as L1_DECISIONS
from .l1_decisions.postgres import (
    create_postgres_l1_decisions,
    create_postgres_readonly_l1_decisions,
)
from .lookups.base import STORE_KIND as LOOKUPS
from .lookups.postgres import create_postgres_lookups
from .records.base import READONLY_STORE_KIND as READONLY_RECORDS
from .records.base import STORE_KIND as RECORDS
from .records.postgres import create_postgres_readonly_records, create_postgres_records

# Kinds whose writable half is registered by entry point (pyproject.toml).
READONLY_TICKETS = "readonly_tickets"
READONLY_AGENT_LOG = "readonly_agent_log"


# The ``postgresql`` Ticket and Agent Log modules import ``soc.l1``, which imports
# this package, so they are imported when the store is opened instead of here:
# at module level, whichever of the two is imported first sees the other half-built.


def _readonly_ticket_store(settings: Settings, environ: Mapping[str, str]):
    """Open ``postgresql.readonly_tickets``."""
    from .postgresql.tickets import create_postgresql_readonly_ticket_store

    return create_postgresql_readonly_ticket_store(settings, environ)


def _readonly_agent_log_store(settings: Settings, environ: Mapping[str, str]):
    """Open ``postgresql.readonly_agent_log``."""
    from .postgresql.agent_log import create_postgresql_readonly_agent_log_store

    return create_postgresql_readonly_agent_log_store(settings, environ)


STORES = PluginRegistry("stores")
STORES.register(f"postgresql.{RECORDS}", create_postgres_records)
STORES.register(f"postgresql.{LOOKUPS}", create_postgres_lookups)
STORES.register(f"postgresql.{READONLY_RECORDS}", create_postgres_readonly_records)
STORES.register(f"postgresql.{BRANCHES}", create_postgres_branches)
STORES.register(f"postgresql.{READONLY_BRANCHES}", create_postgres_readonly_branches)
STORES.register(f"postgresql.{L1_DECISIONS}", create_postgres_l1_decisions)
STORES.register(f"postgresql.{READONLY_L1_DECISIONS}", create_postgres_readonly_l1_decisions)
STORES.register(f"postgresql.{READONLY_TICKETS}", _readonly_ticket_store)
STORES.register(f"postgresql.{READONLY_AGENT_LOG}", _readonly_agent_log_store)


def open_store(
    kind: str,
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
    connection: object | None = None,
):
    """Open the ``kind`` store of the configured backend, e.g. ``open_store("records", ...)``.

    ``connection`` is a connection the caller already borrowed from its backend's
    pool, which the screen API does once per request (box 27, #104). It is opaque
    to the core and only passed on when there is one, so a backend that does not
    take it keeps working.
    """
    environ = os.environ if environ is None else environ
    registry = STORES if registry is None else registry
    factory = registry.get(f"{settings.store.backend}.{kind}")
    if connection is None:
        return factory(settings, environ)
    return factory(settings, environ, connection=connection)
