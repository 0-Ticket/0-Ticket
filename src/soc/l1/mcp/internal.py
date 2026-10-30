"""Internal data MCP tools: the stored Alert and Event records (boxes 19, 28, 31, 42, D-041).

Read-only by construction: the store comes from ``ToolContext.records``, which
connects with the read-only account (docs/security-policy.md 4). Records are
returned as stored, so the log strings inside them stay data and nothing in them
decides what a tool does next (docs/security-policy.md 3).
"""

from typing import Any, Literal

from soc.l1.mcp.server import ToolContext, ToolSpec
from soc.store.records.base import ENTITY_FIELDS, EntityField

QUERY_RECORDS = "query_records"
QUERY_RECORDS_DESCRIPTION = (
    "Read the stored alerts (C5) or events (C13) of one entity inside a time window. "
    f"'field' is one of {', '.join(ENTITY_FIELDS)} and 'value' is that entity, times are "
    "UTC epoch milliseconds, 'time_from' counts and 'time_to' does not. Oldest first. "
    "Returns stored records as data; it changes nothing."
)

GET_ALERT = "get_alert"
GET_ALERT_DESCRIPTION = (
    "Read one stored alert (C5) by its alert_id. Returns null if no alert has that id. "
    "Returns the stored record as data; it changes nothing."
)

KINDS = ("alert", "event")


def internal_data_tools(context: ToolContext) -> tuple[ToolSpec, ...]:
    """The internal data tools, ready to register on a tool server."""

    def query_records(
        field: EntityField,
        value: str,
        kind: Literal["alert", "event"],
        time_from: int,
        time_to: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read stored alerts or events about one entity."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        store = context.records()
        find = store.find_alert_records if kind == "alert" else store.find_event_records
        return [
            record.model_dump(mode="json")
            for record in find(field, value, time_from, time_to, limit)
        ]

    def get_alert(alert_id: str) -> dict[str, Any] | None:
        """Read one stored alert by its id."""
        record = context.records().get_alert_record(alert_id)
        return None if record is None else record.model_dump(mode="json")

    return (
        ToolSpec(
            name=QUERY_RECORDS,
            description=QUERY_RECORDS_DESCRIPTION,
            handler=query_records,
            limit_argument="limit",
        ),
        ToolSpec(name=GET_ALERT, description=GET_ALERT_DESCRIPTION, handler=get_alert),
    )
