"""The read-only SIEM MCP tool agents call (box 15, D-035).

L1 (entity lookup), L2 (the same entity's past) and L3 (hypothesis checks) read
the SIEM through this one tool. Which SIEM answers is the adapter's business, so
the tool and the agents stay the same when the SIEM changes, and so do its errors:
``SiemUnavailableError`` or ``SiemAdapterError`` (``base.py``), whatever the SIEM,
each with one fixed message whatever the adapter wrote.
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
# What a caller sees when a query fails. Adapter messages are plugin text that may
# hold secrets, log content or paths, so only the error type crosses the tool.
UNAVAILABLE_MESSAGE = "SIEM cannot be reached"
ADAPTER_ERROR_MESSAGE = "SIEM answer cannot be used"


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
        # Remade, never re-raised: the type survives for the queue's failure_reason, the
        # adapter's message and cause do not (they would reach MCP replies and server logs).
        try:
            records = adapter.query(query)
        except SiemUnavailableError:
            raise SiemUnavailableError(UNAVAILABLE_MESSAGE) from None
        except Exception:  # Adapters are plugin code: any other failure is an adapter error.
            raise SiemAdapterError(ADAPTER_ERROR_MESSAGE) from None
        return to_c2_records(records)

    return (
        ToolSpec(
            name=QUERY_SIEM,
            description=QUERY_SIEM_DESCRIPTION,
            handler=query_siem,
            limit_argument="limit",
        ),
    )
