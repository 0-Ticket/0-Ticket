"""PostgreSQL Ticket store (box 10, D-002, registered as ``postgresql.tickets``)."""

import json
from collections.abc import Mapping
from typing import Any

import psycopg

from soc.config import Settings
from soc.contracts import validate_contract
from soc.db import connect
from soc.l1.tickets import ConcurrentTicketUpdateError, TicketNotFoundError


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


def create_postgresql_ticket_store(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresTicketStore:
    """Factory registered in the ``zero_ticket_soc.stores`` entry point group."""
    return PostgresTicketStore(connect(settings, environ), owns_connection=True)
