"""L2 분류 결과를 Ticket·Incident 한 트랜잭션으로 저장한다."""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, validate_contract
from soc.entities import normalize_entity_value
from soc.ids import new_id
from soc.l2.branch.context import BranchContext
from soc.l2.branch.decide import Decision
from soc.l2.branch.read import _contract_row

_OPEN_STATUSES = ("analyzing", "awaiting_review", "human_handling")
_INCIDENT_COLUMNS = (
    "id",
    "title",
    "summary",
    "status",
    "ticket_ids",
    "entities",
    "severity",
    "assessed_severity",
    "analysis_round",
    "review_round",
    "created_at",
    "updated_at",
    "details",
)


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    incident_id: str | None = None


def save_branch(
    conn: psycopg.Connection,
    context: BranchContext,
    decision: Decision,
    branch_details: dict[str, Any],
    *,
    now_ms: int,
) -> SaveResult:
    """Ticket을 잠가 아직 escalated일 때만 Incident와 함께 저장한다."""
    with conn.transaction():
        ticket_row = _fetch_locked(conn, "tickets", context.ticket["id"])
        if ticket_row is None or ticket_row["status"] != "escalated":
            return SaveResult(False)
        ticket = _contract_row("ticket", ticket_row)

        incident = None
        if decision.incident_id is not None:
            incident_row = _fetch_locked(conn, "incidents", decision.incident_id)
            if incident_row is not None and incident_row["status"] in _OPEN_STATUSES:
                incident = _contract_row("incident", incident_row)
            else:
                branch_details = {
                    **branch_details,
                    "decision_source": "rule_default",
                    "decision_fallback": "incident_closed",
                }

        if incident is None:
            incident = _new_incident(context, ticket, now_ms)
        else:
            incident = _updated_incident(incident, ticket, context, now_ms)

        ticket = {
            **ticket,
            "status": "linked",
            "updated_at": now_ms,
            "details": {**ticket["details"], "l2_branch": branch_details},
        }
        validate_contract("incident", incident)
        validate_contract("ticket", ticket)
        if decision.incident_id is None or decision.incident_id != incident["id"]:
            _insert_incident(conn, incident)
        else:
            _update_incident(conn, incident)
        conn.execute(
            "UPDATE tickets SET status = 'linked', updated_at = %s, details = %s WHERE id = %s",
            (to_datetime(now_ms), Jsonb(ticket["details"]), ticket["id"]),
        )
        return SaveResult(True, incident["id"])


def _new_incident(context: BranchContext, ticket: dict[str, Any], now_ms: int) -> dict[str, Any]:
    return {
        "id": new_id("inc"),
        "title": _title(context, ticket),
        "summary": None,
        "status": "analyzing",
        "ticket_ids": [ticket["id"]],
        "entities": ticket["entities"],
        "severity": _ticket_severity(context),
        "assessed_severity": None,
        "analysis_round": 0,
        "review_round": 0,
        "created_at": now_ms,
        "updated_at": now_ms,
        "details": {},
    }


def _updated_incident(
    incident: dict[str, Any],
    ticket: dict[str, Any],
    context: BranchContext,
    now_ms: int,
) -> dict[str, Any]:
    ticket_ids = list(incident["ticket_ids"])
    if ticket["id"] not in ticket_ids:
        ticket_ids.append(ticket["id"])
    return {
        **incident,
        "status": "analyzing" if incident["status"] == "awaiting_review" else incident["status"],
        "ticket_ids": ticket_ids,
        "entities": _merge_entities(incident["entities"], ticket["entities"]),
        "severity": max(incident["severity"], _ticket_severity(context)),
        "updated_at": now_ms,
    }


def _merge_entities(
    existing: list[dict[str, Any]], added: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out = list(existing)
    seen = {(e["type"], normalize_entity_value(e["type"], e["value"])) for e in existing}
    for entity in added:
        key = (entity["type"], normalize_entity_value(entity["type"], entity["value"]))
        if key not in seen:
            seen.add(key)
            out.append(entity)
    return out


def _ticket_severity(context: BranchContext) -> int:
    return max((alert["severity"] for alert in context.alerts), default=0)


def _title(context: BranchContext, ticket: dict[str, Any]) -> str:
    if context.alerts and context.alerts[0]["title"]:
        return context.alerts[0]["title"]
    if context.hunt is not None and context.hunt["hypothesis"]:
        return context.hunt["hypothesis"]
    if ticket["entities"]:
        return ticket["entities"][0]["value"]
    return ticket["id"]


def _fetch_locked(conn: psycopg.Connection, table: str, row_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT * FROM {table} WHERE id = %s FOR UPDATE",  # table은 이 모듈 상수만 받는다
            (row_id,),
        ).fetchone()


def _insert_incident(conn: psycopg.Connection, incident: dict[str, Any]) -> None:
    values = [_db_value(column, incident[column]) for column in _INCIDENT_COLUMNS]
    conn.execute(
        f"INSERT INTO incidents ({', '.join(_INCIDENT_COLUMNS)}) "
        f"VALUES ({', '.join(['%s'] * len(_INCIDENT_COLUMNS))})",
        values,
    )


def _update_incident(conn: psycopg.Connection, incident: dict[str, Any]) -> None:
    columns = [column for column in _INCIDENT_COLUMNS if column not in ("id", "created_at")]
    conn.execute(
        f"UPDATE incidents SET {', '.join(f'{column} = %s' for column in columns)} WHERE id = %s",
        [*(_db_value(column, incident[column]) for column in columns), incident["id"]],
    )


def _db_value(column: str, value: Any) -> Any:
    if column in ("created_at", "updated_at"):
        return to_datetime(value)
    if column in ("entities", "details"):
        return Jsonb(value)
    return value
