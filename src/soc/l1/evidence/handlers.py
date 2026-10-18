"""Built-in evidence handlers (box 26 -> box 15).

Only ``siem_mcp`` is built in. ``lookup`` waits for box 5 (issue 1-6) and
``specialist_agent`` for box 14 (issue 3-4); until then a request of those
types fails as unhandled, so no made-up result can reach an L1 decision.
"""

from collections.abc import Mapping
from typing import Any

from soc.l1.mcp.server import ToolServer
from soc.l1.mcp.siem.tools import QUERY_SIEM

from .base import EvidenceHandler


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


def default_handlers(tools: ToolServer) -> dict[str, EvidenceHandler]:
    """The handlers the queue worker runs with, keyed by C22 ``request_type``."""
    return {"siem_mcp": siem_mcp_handler(tools)}
