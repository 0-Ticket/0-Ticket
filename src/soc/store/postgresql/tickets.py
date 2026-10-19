"""PostgreSQL Ticket store (box 10, D-002, registered as ``postgresql.tickets``)."""

import json
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql

from soc.config import Settings
from soc.contracts import validate_contract
from soc.db import connect, connect_readonly
from soc.l1.tickets import (
    ConcurrentTicketUpdateError,
    TicketNotFoundError,
    TicketPage,
    check_ticket_list_args,
    decode_ticket_cursor,
    ticket_cursor,
)
from soc.store.paging import DEFAULT_PAGE_LIMIT

# GET /api/tickets order; ticket_id compares by code point like Python (migration 0092).
_PRIORITY = sql.SQL("((payload ->> 'priority')::bigint)")
_CREATED_AT = sql.SQL("((payload ->> 'created_at')::bigint)")
_TICKET_ID = sql.SQL('(ticket_id COLLATE "C")')


def _ticket_dict(ticket: Mapping[str, Any]) -> dict[str, Any]:
    return validate_contract("Ticket", dict(ticket)).model_dump(mode="json")


def _ticket_json(ticket: Mapping[str, Any]) -> str:
    return json.dumps(ticket, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _decode_ticket(payload: Any) -> dict[str, Any]:
    value = json.loads(payload) if isinstance(payload, str) else payload
    return _ticket_dict(value)


class PostgresTicketStore:
    """Persist C6 JSON and an indexed entity relation in PostgreSQL."""

    def __init__(self, connection: psycopg.Connection, *, owns_connection: bool = False):
        self._connection = connection
        self._owns_connection = owns_connection

    def create(self, ticket: Mapping[str, Any]) -> dict[str, Any]:
        validated = _ticket_dict(ticket)
        with self._connection.transaction():
            self._connection.execute(
                "INSERT INTO tickets (ticket_id, payload) VALUES (%s, %s::jsonb)",
                (validated["ticket_id"], _ticket_json(validated)),
            )
            self._replace_entities(validated["ticket_id"], validated["entities"])
        return validated

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload FROM tickets WHERE ticket_id = %s", (ticket_id,)
        ).fetchone()
        return None if row is None else _decode_ticket(row[0])

    def find_by_entity(self, entity_type: str, entity_value: str) -> list[dict[str, Any]]:
        validate_contract("Entity", {"type": entity_type, "value": entity_value})
        rows = self._connection.execute(
            """
            SELECT tickets.payload
            FROM tickets
            JOIN ticket_entities USING (ticket_id)
            WHERE ticket_entities.entity_type = %s
              AND ticket_entities.entity_value = %s
            ORDER BY tickets.ticket_id
            """,
            (entity_type, entity_value),
        ).fetchall()
        return [_decode_ticket(row[0]) for row in rows]

    def update(self, ticket: Mapping[str, Any], *, expected_status: str) -> dict[str, Any]:
        validated = _ticket_dict(ticket)
        ticket_id = validated["ticket_id"]
        with self._connection.transaction():
            row = self._connection.execute(
                "SELECT payload FROM tickets WHERE ticket_id = %s FOR UPDATE", (ticket_id,)
            ).fetchone()
            if row is None:
                raise TicketNotFoundError("Ticket not found")
            current = _decode_ticket(row[0])
            if current["status"] != expected_status:
                raise ConcurrentTicketUpdateError("Ticket status changed before update")
            self._connection.execute(
                "UPDATE tickets SET payload = %s::jsonb WHERE ticket_id = %s",
                (_ticket_json(validated), ticket_id),
            )
            self._replace_entities(ticket_id, validated["entities"])
        return validated

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def _replace_entities(self, ticket_id: str, entities: list[dict[str, Any]]) -> None:
        self._connection.execute("DELETE FROM ticket_entities WHERE ticket_id = %s", (ticket_id,))
        if entities:
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO ticket_entities (ticket_id, entity_type, entity_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [(ticket_id, entity["type"], entity["value"]) for entity in entities],
                )

    # Last in the class: the method name shadows the built-in list in the class body.
    def list(
        self,
        *,
        status: str | None = None,
        origin: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> TicketPage:
        check_ticket_list_args(status, origin, limit)
        after = decode_ticket_cursor(cursor)
        conditions, params = [], []
        for key, value in (("status", status), ("origin", origin)):
            if value is not None:
                conditions.append(sql.SQL("payload ->> {} = %s").format(sql.Literal(key)))
                params.append(value)
        if after is not None:
            priority, created_at, ticket_id = after
            conditions.append(
                sql.SQL("({p} < %s OR ({p} = %s AND ({c}, {t}) > (%s, %s)))").format(
                    p=_PRIORITY, c=_CREATED_AT, t=_TICKET_ID
                )
            )
            params.extend([priority, priority, created_at, ticket_id])
        where = (
            sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
        )
        query = sql.SQL(
            "SELECT payload FROM tickets{w} ORDER BY {p} DESC, {c}, {t} LIMIT %s"
        ).format(w=where, p=_PRIORITY, c=_CREATED_AT, t=_TICKET_ID)
        rows = self._connection.execute(query, [*params, limit + 1]).fetchall()
        items = [_decode_ticket(row[0]) for row in rows[:limit]]
        next_cursor = ticket_cursor(items[-1]) if len(rows) > limit else None
        return TicketPage(items, next_cursor)


def create_postgresql_ticket_store(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresTicketStore:
    """Factory registered in the ``zero_ticket_soc.stores`` entry point group."""
    return PostgresTicketStore(connect(settings, environ), owns_connection=True)


def create_postgresql_readonly_ticket_store(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresTicketStore:
    """The ``postgresql.readonly_tickets`` factory: reads and lists work, every write fails.

    For the screen API (box 27), which only reads Tickets (docs/security-policy.md 4).
    """
    return PostgresTicketStore(connect_readonly(settings, environ), owns_connection=True)
