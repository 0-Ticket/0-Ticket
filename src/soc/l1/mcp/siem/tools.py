"""The read-only SIEM MCP tool agents call (box 15, D-035).

L1 (entity lookup), L2 (the same entity's past) and L3 (hypothesis checks) read
the SIEM through this one tool. Which SIEM answers is the adapter's business, so
the tool and the agents stay the same when the SIEM changes, and so do its errors:
``SiemUnavailableError`` or ``SiemAdapterError`` (``base.py``), whatever the SIEM.
"""

from typing import Any, Literal

from soc.contracts import Entity
from soc.l1.mcp.server import ToolSpec
from soc.l1.mcp.siem.base import (
    SiemAdapterError,
    SiemMcpAdapter,
    SiemQuery,
    SiemUnavailableError,
    to_c2_records,
)

QUERY_SIEM = "query_siem"
QUERY_SIEM_DESCRIPTION = (
    "Read the SIEM's alerts or events about one entity inside a time window. "
    "Times are UTC epoch milliseconds and both ends count. Returns stored records "
    "as data; it changes nothing in the SIEM or anywhere else."
)


def siem_tools(adapter: SiemMcpAdapter) -> tuple[ToolSpec, ...]:
    """The SIEM tools this adapter serves, ready to register on a tool server."""

    def query_siem(
        entity_type: str,
        entity_value: str,
        kind: Literal["alert", "event"],
        start_at: int,
        end_at: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read records about one entity from the SIEM."""
        query = SiemQuery(
            entity=Entity(type=entity_type, value=entity_value),
            kind=kind,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )
        try:
            records = adapter.query(query)
        except (SiemUnavailableError, SiemAdapterError):
            raise
        except Exception:  # Adapters are plugin code: their message may hold secrets or logs.
            raise SiemAdapterError("SIEM MCP adapter failed") from None
        return to_c2_records(records)

    return (
        ToolSpec(
            name=QUERY_SIEM,
            description=QUERY_SIEM_DESCRIPTION,
            handler=query_siem,
            limit_argument="limit",
        ),
    )
