"""Built-in evidence handlers (box 26 -> boxes 15, 14 and 5).

- ``siem_mcp``: reads the SIEM through the MCP tool server.
- ``lookup``: asks the configured lookup provider (the same one the
  normalization join uses) through ``LookupEnricher``, so its output is checked as C4.
- ``specialist_agent``: hands the question to the specialist registered for the
  request's domain (boxes 13, 14), which answers with a C14.
"""

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from soc.l1.mcp.server import ToolServer
from soc.l1.mcp.siem.tools import QUERY_SIEM
from soc.l1.specialists import DEFAULT_DOMAIN, SpecialistContext, open_specialist
from soc.normalize.lookup.base import LookupProvider
from soc.normalize.lookup.enricher import LookupEnricher
from soc.plugins import PluginRegistry

from .base import EvidenceHandler

logger = logging.getLogger(__name__)

# Entity types the Lookup tables hold: IP and host name -> asset, user -> account.
ASSET_ENTITY_TYPES = frozenset({"ip", "host"})
USER_ENTITY_TYPES = frozenset({"user"})


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def siem_mcp_handler(tools: ToolServer) -> EvidenceHandler:
    """Read the SIEM through the ``query_siem`` tool, with the requesting agent's allowlist."""

    def handle(request: Mapping[str, Any], *, agent: str) -> dict[str, Any]:
        params = request["params"]
        records = tools.call(
            agent,
            QUERY_SIEM,
            entity_type=params["entity"]["type"],
            entity_value=params["entity"]["value"],
            kind=params["kind"],
            start_at=params["start_at"],
            end_at=params["end_at"],
            limit=params["limit"],
        )
        return {"records": records}

    return handle


def lookup_handler(enricher: LookupEnricher, clock: Callable[[], int] = _now_ms) -> EvidenceHandler:
    """C22 lookup ``{entity, at}`` -> ``{asset, user}``. ``at`` null means now.

    Nothing found is still a result: both null. An entity type the tables do not
    hold also gives both null, with a warning that names the type, not the value.
    """

    def handle(request: Mapping[str, Any], *, agent: str) -> dict[str, Any]:
        params = request["params"]
        entity = params["entity"]
        at = params["at"]
        at = clock() if at is None else at
        asset = user = None
        if entity["type"] in ASSET_ENTITY_TYPES:
            asset = enricher.asset(entity["value"], at)
        elif entity["type"] in USER_ENTITY_TYPES:
            user = enricher.user(entity["value"], at)
        else:
            logger.warning(
                "Lookup holds no table for entity type %r; returning no match", entity["type"]
            )
        return {"asset": _dump(asset), "user": _dump(user)}

    return handle


def specialist_agent_handler(
    context: SpecialistContext, registry: PluginRegistry | None = None
) -> EvidenceHandler:
    """C22 ``specialist_agent`` -> ``{finding}`` from the specialist of the request's domain.

    The requesting agent is not passed on: a specialist reads tools under its own
    allowlist, so who asked cannot widen what it may read.
    """

    def handle(request: Mapping[str, Any], *, agent: str) -> dict[str, Any]:
        domain = request["domain"] or DEFAULT_DOMAIN
        return {"finding": open_specialist(domain, context, registry)(request)}

    return handle


def default_handlers(
    context: SpecialistContext, lookup: LookupProvider, clock: Callable[[], int] = _now_ms
) -> dict[str, EvidenceHandler]:
    """The handlers the queue worker runs with, keyed by C22 ``request_type``.

    ``context`` is what a specialist is built from (box 14); its tool server is
    the one the SIEM handler reads through too. ``lookup`` is the provider
    ``open_lookup`` gave, shared with the normalization join.
    """
    return {
        "siem_mcp": siem_mcp_handler(context.tools),
        "lookup": lookup_handler(LookupEnricher(lookup), clock),
        "specialist_agent": specialist_agent_handler(context),
    }


def _dump(model):
    return None if model is None else model.model_dump(mode="json")
