"""L2 분류에 필요한 기존 행을 읽는다. 이 모듈은 DB에 쓰지 않는다."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.contracts import to_epoch_ms, validate_contract

_OPEN_STATUSES = ("analyzing", "awaiting_review", "human_handling")
_CLOSED_STATUSES = ("confirmed", "dismissed")
_RECENT_INCIDENTS_QUERY = """
SELECT * FROM incidents
WHERE status = ANY(%s) AND updated_at >= %s AND updated_at <= %s
ORDER BY updated_at DESC
LIMIT %s
"""

_TIME_FIELDS = {
    "alert": ("time",),
    "event": ("time",),
    "ticket": ("created_at", "updated_at"),
    "incident": ("created_at", "updated_at"),
    "hunt": ("verified_at", "created_at", "updated_at"),
}


@dataclass(frozen=True)
class BranchRows:
    ticket: dict[str, Any]
    alerts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    hunt: dict[str, Any] | None
    evidence_ids: tuple[str, ...]
    missing_evidence_count: int


@dataclass(frozen=True)
class IncidentLookup:
    open: dict[str, dict[str, Any]]
    closed_ids: tuple[str, ...]


def read_branch_data(
    conn: psycopg.Connection,
    ticket_id: str,
    *,
    expected_status: str = "escalated",
) -> BranchRows:
    """Ticket 하나와 Alert·Event·Hunt 근거를 읽는다. Incident는 읽지 않는다."""

    ticket_row = _fetch_one(conn, "SELECT * FROM tickets WHERE id = %s", (ticket_id,))
    if ticket_row is None:
        raise LookupError("Ticket을 찾지 못했다")
    ticket = _contract_row("ticket", ticket_row)
    if ticket["status"] != expected_status:
        raise ValueError(f"Ticket status는 {expected_status}여야 한다")

    alerts = _contract_rows(
        "alert", _fetch_by_ids(conn, "alerts", ticket["alert_ids"]), ticket["alert_ids"]
    )
    if len(alerts) != len(ticket["alert_ids"]):
        raise LookupError("Ticket의 Alert를 찾지 못했다")

    hunt = None
    if ticket["origin"] == "l3":
        hunt_row = _fetch_one(conn, "SELECT * FROM hunts WHERE id = %s", (ticket["hunt_id"],))
        if hunt_row is None:
            raise LookupError("Ticket의 Hunt를 찾지 못했다")
        hunt = _contract_row("hunt", hunt_row)

    evidence = [] if ticket["verdict"] is None else ticket["verdict"]["evidence_ids"]
    if hunt is not None:
        evidence = [*evidence, *hunt["evidence_ids"]]
    evidence_ids = tuple(dict.fromkeys(evidence))

    event_ids = [item for item in evidence_ids if item.startswith("evt_")]
    event_rows = _fetch_by_ids(conn, "events", event_ids)
    events = _contract_rows("event", event_rows, event_ids)
    existing = {event["id"] for event in events}
    existing |= _existing_ids(
        conn, "alerts", [item for item in evidence_ids if item.startswith("alt_")]
    )
    existing |= _existing_ids(
        conn, "agent_logs", [item for item in evidence_ids if item.startswith("agl_")]
    )
    confirmed_evidence = tuple(item for item in evidence_ids if item in existing)

    return BranchRows(
        ticket=ticket,
        alerts=alerts,
        events=events,
        hunt=hunt,
        evidence_ids=confirmed_evidence,
        missing_evidence_count=len(evidence_ids) - len(confirmed_evidence),
    )


def read_recent_incidents(
    conn: psycopg.Connection,
    now: datetime,
    candidate_window_ms: int,
    *,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    """시간 창 안의 열린 Incident를 최근 갱신 순으로 limit개 읽는다."""
    _check_window(now, candidate_window_ms)
    if limit <= 0:
        raise ValueError("limit은 양수여야 한다")
    cutoff = now - timedelta(milliseconds=candidate_window_ms)
    rows = _fetch_all(
        conn,
        _RECENT_INCIDENTS_QUERY,
        (list(_OPEN_STATUSES), cutoff, now, limit),
    )
    return tuple(_contract_row("incident", row) for row in rows)


def read_incidents_by_ids(
    conn: psycopg.Connection,
    incident_ids: list[str],
    now: datetime,
    candidate_window_ms: int,
) -> IncidentLookup:
    """vector가 가리킨 Incident 중 열린 최근 행과 닫힌 ID를 나눈다."""
    _check_window(now, candidate_window_ms)
    cutoff = now - timedelta(milliseconds=candidate_window_ms)
    rows = _fetch_by_ids(conn, "incidents", incident_ids)
    opened = {}
    closed = []
    for incident_id in incident_ids:
        row = rows.get(incident_id)
        if row is None:
            continue
        if row["status"] in _CLOSED_STATUSES:
            closed.append(incident_id)
        elif row["status"] in _OPEN_STATUSES and cutoff <= row["updated_at"] <= now:
            opened[incident_id] = _contract_row("incident", row)
    return IncidentLookup(opened, tuple(dict.fromkeys(closed)))


def read_hit_tickets(conn: psycopg.Connection, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
    """hit Ticket과 대표 Alert 제목 또는 Hunt 가설을 한 묶음으로 읽는다."""
    rows = _fetch_by_ids(conn, "tickets", ticket_ids)
    tickets = {
        ticket_id: _contract_row("ticket", rows[ticket_id])
        for ticket_id in ticket_ids
        if ticket_id in rows
    }
    alert_ids = [ticket["alert_ids"][0] for ticket in tickets.values() if ticket["alert_ids"]]
    hunt_ids = [
        ticket["hunt_id"]
        for ticket in tickets.values()
        if ticket["origin"] == "l3" and ticket["hunt_id"] is not None
    ]
    alerts = _fetch_by_ids(conn, "alerts", alert_ids)
    hunts = _fetch_by_ids(conn, "hunts", hunt_ids)
    out = {}
    for ticket_id, ticket in tickets.items():
        title = None
        if ticket["alert_ids"]:
            alert = alerts.get(ticket["alert_ids"][0])
            if alert is not None:
                title = _contract_row("alert", alert)["title"]
        elif ticket["hunt_id"] is not None:
            hunt = hunts.get(ticket["hunt_id"])
            if hunt is not None:
                title = _contract_row("hunt", hunt)["hypothesis"]
        out[ticket_id] = {**ticket, "title": title}
    return out


def _check_window(now: datetime, candidate_window_ms: int) -> None:
    to_epoch_ms(now)
    if candidate_window_ms <= 0:
        raise ValueError("candidate_window_ms는 양수여야 한다")


def _fetch_one(
    conn: psycopg.Connection, query: str, params: tuple[object, ...]
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, params).fetchone()


def _fetch_all(
    conn: psycopg.Connection, query: str, params: tuple[object, ...]
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, params).fetchall()


def _fetch_by_ids(
    conn: psycopg.Connection, table: str, ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    query = f"SELECT * FROM {table} WHERE id = ANY(%s)"  # table은 이 모듈의 상수만 받는다
    return {row["id"]: row for row in _fetch_all(conn, query, (ids,))}


def _existing_ids(conn: psycopg.Connection, table: str, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    query = f"SELECT id FROM {table} WHERE id = ANY(%s)"  # table은 이 모듈의 상수만 받는다
    return {row["id"] for row in _fetch_all(conn, query, (ids,))}


def _contract_rows(
    name: str, rows: dict[str, dict[str, Any]], ids: list[str]
) -> tuple[dict[str, Any], ...]:
    return tuple(_contract_row(name, rows[row_id]) for row_id in ids if row_id in rows)


def _contract_row(name: str, row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for field in _TIME_FIELDS[name]:
        if data[field] is not None:
            data[field] = to_epoch_ms(data[field])
    return validate_contract(name, data).model_dump(mode="json")
