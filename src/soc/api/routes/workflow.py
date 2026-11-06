"""Ticket → Incident → Case 읽기. 승인이나 상태 변경은 하지 않는다."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from soc.api import db
from soc.api import ui_read as read
from soc.api.routes.records import Cursor, Limit
from soc.api.ui_models import (
    CaseDetail,
    CasePage,
    CaseStatus,
    IncidentDetail,
    IncidentPage,
    IncidentStatus,
    TicketDetail,
    TicketOrigin,
    TicketPage,
    TicketStatus,
)

router = APIRouter()


@router.get("/tickets", response_model=TicketPage)
def tickets(
    request: Request,
    status: TicketStatus | None = None,
    origin: TicketOrigin | None = None,
    severity: Annotated[int | None, Query(ge=0, le=6)] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
):
    if cursor:
        read.check_id(cursor, ("tkt",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.read_page(
            conn,
            "tickets",
            read.TICKET_COLUMNS,
            "t",
            [("t.status", status), ("t.origin", origin), (read.TICKET_SEVERITY, severity)],
            cursor,
            limit,
        )


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def ticket(request: Request, ticket_id: str):
    read.check_id(ticket_id, ("tkt",))
    with db.connect(request.app.state.settings) as conn:
        row = read.detail(conn, "tickets", "tkt", ticket_id)
        severity = conn.execute(
            "SELECT COALESCE(max(severity),0) AS severity FROM alerts WHERE id=ANY(%s)",
            (row["alert_ids"],),
        ).fetchone()["severity"]
    return dict(ticket=row, severity=severity, seed_source=row["details"].get("seed_source"))


@router.get("/incidents", response_model=IncidentPage)
def incidents(
    request: Request, status: IncidentStatus | None = None, cursor: Cursor = None, limit: Limit = 50
):
    if cursor:
        read.check_id(cursor, ("inc",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.read_page(
            conn, "incidents", read.INCIDENT_COLUMNS, "i", [("i.status", status)], cursor, limit
        )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def incident(request: Request, incident_id: str):
    read.check_id(incident_id, ("inc",))
    with db.connect(request.app.state.settings) as conn:
        row = read.detail(conn, "incidents", "inc", incident_id)
        artifacts = conn.execute(
            "SELECT * FROM incident_artifacts WHERE incident_id=%s ORDER BY analysis_round DESC",
            (incident_id,),
        ).fetchall()
        proposals = conn.execute(
            "SELECT p.* FROM incident_proposals p JOIN incident_artifacts a "
            "ON a.id=p.artifact_id WHERE a.incident_id=%s "
            "ORDER BY a.analysis_round DESC,p.kind,p.seq",
            (incident_id,),
        ).fetchall()
    return dict(
        incident=row,
        artifacts=[read.times(x) for x in artifacts],
        proposals=[read.times(x) for x in proposals],
        seed_source=row["details"].get("seed_source"),
    )


@router.get("/cases", response_model=CasePage)
def cases(
    request: Request, status: CaseStatus | None = None, cursor: Cursor = None, limit: Limit = 50
):
    if cursor:
        read.check_id(cursor, ("cas",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.read_page(
            conn, "cases", read.CASE_COLUMNS, "c", [("c.status", status)], cursor, limit
        )


@router.get("/cases/{case_id}", response_model=CaseDetail)
def case(request: Request, case_id: str):
    read.check_id(case_id, ("cas",))
    with db.connect(request.app.state.settings) as conn:
        row = read.detail(conn, "cases", "cas", case_id)
    return dict(case=row, seed_source=row["details"].get("seed_source"))
