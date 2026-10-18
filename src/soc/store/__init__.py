"""Stores (boxes 5, 6, 7, 10, 12, ... D-002): one ``stores`` registry for every kind of store.

Implementations are registered as ``<backend>.<kind>``: ``postgresql.records``
for Alert/Event (boxes 6, 7), ``postgresql.tickets``, and ``postgresql.agent_log``.
``[store] backend`` picks the backend for all of them; the core passes only the
kind to ``open_store`` and never names a backend.
"""

import os
from collections.abc import Mapping

from soc.config import Settings
from soc.plugins import PluginRegistry

from .records.base import STORE_KIND as RECORDS
from .records.postgres import create_postgres_records

STORES = PluginRegistry("stores")
STORES.register(f"postgresql.{RECORDS}", create_postgres_records)


def open_store(
    kind: str,
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
):
    """Open the ``kind`` store of the configured backend, e.g. ``open_store("records", ...)``."""
    environ = os.environ if environ is None else environ
    registry = STORES if registry is None else registry
    factory = registry.get(f"{settings.store.backend}.{kind}")
    return factory(settings, environ)
