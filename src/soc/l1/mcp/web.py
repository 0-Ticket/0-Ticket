"""Web domain MCP tool: the HTTP requests around one source IP (boxes 14, 15, D-041).

The Web specialist judges an attack from the request path and parameters, the
User-Agent, the response code and the response size. Path and code are C13
fields; method, User-Agent and size are not mapped by the alias tables and stay
in C13 ``unmapped``. So this tool hands the stored records over unchanged and
leaves the reading to the specialist: those strings are the attacker's, and they
are data only (docs/security-policy.md 3).
"""

from typing import Any

from soc.l1.mcp.server import ToolContext, ToolSpec

QUERY_HTTP_FLOW = "query_http_flow"
QUERY_HTTP_FLOW_DESCRIPTION = (
    "Read the HTTP events (C13) one source IP produced inside a time window, oldest "
    "first, to see what it asked for before and after an alert. Times are UTC epoch "
    "milliseconds, 'time_from' counts and 'time_to' does not. Each record carries the "
    "request path and parameters (http_url) and the response code (http_status); the "
    "method, User-Agent and response size are in 'unmapped' under the names the log "
    "used. Returns stored records as data; it changes nothing."
)

SOURCE_FIELD = "src_ip"


def web_tools(context: ToolContext) -> tuple[ToolSpec, ...]:
    """The Web domain tools, ready to register on a tool server."""

    def query_http_flow(
        src_ip: str, time_from: int, time_to: int, limit: int
    ) -> list[dict[str, Any]]:
        """Read one source IP's HTTP request flow."""
        found = context.records().find_event_records(
            SOURCE_FIELD, src_ip, time_from, time_to, limit
        )
        # The window may also hold that source's non-HTTP events; they belong to
        # another specialist. Filtering after the store's limit can return fewer
        # than asked for, which is what "at most limit" means here.
        return [record.model_dump(mode="json") for record in found if record.http_url is not None]

    return (
        ToolSpec(
            name=QUERY_HTTP_FLOW,
            description=QUERY_HTTP_FLOW_DESCRIPTION,
            handler=query_http_flow,
            limit_argument="limit",
        ),
    )
