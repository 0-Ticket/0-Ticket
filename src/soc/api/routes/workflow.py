"""Ticket → Incident → Case 읽기와 Incident 승인·반려(#365, D-076). Case 상태 변경은 없다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from soc.api import db
from soc.api import ui_read as read
from soc.api import ui_write as write
from soc.api.auth import require_permission
from soc.api.routes.records import Cursor, Limit
from soc.api.ui_models import (
    CaseDetail,
    CasePage,
    CaseStatus,
    IncidentDetail,
    IncidentPage,
    IncidentStatus,
    ReviewResult,
    TicketDetail,
    TicketOrigin,
    TicketPage,
    TicketStatus,
)
from soc.auth.store import User

router = APIRouter()
Approver = Annotated[User, Depends(require_permission("incident.approve"))]
Rejecter = Annotated[User, Depends(require_permission("incident.reject"))]


@router.get(
    "/tickets", response_model=TicketPage, dependencies=[Depends(require_permission("ticket.read"))]
)
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
        page = read.read_page(
            conn,
            "tickets",
            read.TICKET_COLUMNS,
            "t",
            [("t.status", status), ("t.origin", origin), (read.TICKET_SEVERITY, severity)],
            cursor,
            limit,
        )
        incidents = read.ticket_incidents(conn, [item["id"] for item in page["items"]])
    for item in page["items"]:
        item["incident"] = incidents.get(item["id"])
    return page


@router.get(
    "/tickets/{ticket_id}",
    response_model=TicketDetail,
    dependencies=[Depends(require_permission("ticket.read"))],
)
def ticket(request: Request, ticket_id: str):
    read.check_id(ticket_id, ("tkt",))
    with db.connect(request.app.state.settings) as conn:
        row = read.detail(conn, "tickets", "tkt", ticket_id)
        severity = conn.execute(
            "SELECT COALESCE(max(severity),0) AS severity FROM alerts WHERE id=ANY(%s)",
            (row["alert_ids"],),
        ).fetchone()["severity"]
        incident = read.ticket_incidents(conn, [ticket_id]).get(ticket_id)
        alerts = read.alert_summaries(conn, row["alert_ids"])
    return dict(
        ticket=row,
        alerts=alerts,
        severity=severity,
        seed_source=row["details"].get("seed_source"),
        incident=incident,
    )


@router.get(
    "/incidents",
    response_model=IncidentPage,
    dependencies=[Depends(require_permission("incident.read"))],
)
def incidents(
    request: Request, status: IncidentStatus | None = None, cursor: Cursor = None, limit: Limit = 50
):
    if cursor:
        read.check_id(cursor, ("inc",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.read_page(
            conn, "incidents", read.INCIDENT_COLUMNS, "i", [("i.status", status)], cursor, limit
        )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetail,
    dependencies=[Depends(require_permission("incident.read"))],
)
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
            "ORDER BY a.analysis_round DESC,p.seq",
            (incident_id,),
        ).fetchall()
        ticket_rows = conn.execute(
            f"SELECT t.id, t.title, t.details, t.verdict, t.alert_ids, t.entities, t.created_at, "
            f"{read.TICKET_SEVERITY} AS severity FROM tickets t WHERE t.id = ANY(%s)",
            (row["ticket_ids"],),
        ).fetchall()
        alerts = read.incident_alerts(conn, [a for item in ticket_rows for a in item["alert_ids"]])
    criticality = read.entity_criticality(alerts)
    by_ticket = {item["id"]: item["details"].get("l2_branch") for item in ticket_rows}
    titles = {item["id"]: item["title"] for item in ticket_rows}
    verdicts = {item["id"]: item["verdict"] or {} for item in ticket_rows}
    by_id = {item["id"]: read.times(item) for item in ticket_rows}
    ticket_graphs = []
    for ticket_id in row["ticket_ids"]:
        graph = by_ticket.get(ticket_id)
        chosen = (
            next(
                (
                    item
                    for item in graph.get("candidates", [])
                    if item.get("incident_id") == incident_id
                ),
                None,
            )
            if graph
            else None
        )
        paths = [] if graph is None else graph.get("paths", [])
        ticket_graphs.append(
            {
                "ticket_id": ticket_id,
                "coverage": "legacy" if graph is None else graph.get("coverage", "unknown"),
                "reason": None if graph is None else graph.get("reason"),
                "paths": paths,
                "vector_only": chosen is not None
                and not any(path.get("incident_id") == incident_id for path in paths),
                "candidate_count": 0 if graph is None else len(graph.get("candidates", [])),
                "vector_score": None if chosen is None else chosen.get("score"),
                "representative_ticket_id": None if chosen is None else chosen.get("ticket_id"),
            }
        )
    return dict(
        incident=row,
        tickets=[
            {
                "id": i,
                "title": titles[i],
                "decision": verdicts[i].get("decision"),
                "severity": by_id[i]["severity"],
                "created_at": by_id[i]["created_at"],
                "evidence_count": len(verdicts[i].get("evidence_ids", [])),
                "alert_ids": by_id[i]["alert_ids"],
                "entities": by_id[i]["entities"],
            }
            for i in row["ticket_ids"]
            if i in titles
        ],
        alerts=[{k: a[k] for k in ("id", "time", "entities")} for a in alerts],
        artifacts=[read.times(x) for x in artifacts],
        proposals=[read.times(x) for x in proposals],
        ticket_graphs=ticket_graphs,
        entity_criticality=criticality,
        seed_source=row["details"].get("seed_source"),
    )


@router.post("/incidents/{incident_id}/approve", response_model=ReviewResult)
def approve_incident(request: Request, incident_id: str, user: Approver):
    read.check_id(incident_id, ("inc",))
    with db.connect_write(request.app.state.settings) as conn:
        return write.approve_incident(conn, incident_id, user.username)


@router.post("/incidents/{incident_id}/reject", response_model=ReviewResult)
def reject_incident(request: Request, incident_id: str, _user: Rejecter):
    read.check_id(incident_id, ("inc",))
    with db.connect_write(request.app.state.settings) as conn:
        return write.reject_incident(conn, incident_id)


@router.get(
    "/cases", response_model=CasePage, dependencies=[Depends(require_permission("case.read"))]
)
def cases(
    request: Request, status: CaseStatus | None = None, cursor: Cursor = None, limit: Limit = 50
):
    if cursor:
        read.check_id(cursor, ("cas",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.read_page(
            conn, "cases", read.CASE_COLUMNS, "c", [("c.status", status)], cursor, limit
        )


@router.get(
    "/cases/{case_id}",
    response_model=CaseDetail,
    dependencies=[Depends(require_permission("case.read"))],
)
def case(request: Request, case_id: str):
    read.check_id(case_id, ("cas",))
    with db.connect(request.app.state.settings) as conn:
        row = read.detail(conn, "cases", "cas", case_id)
    return dict(case=row, seed_source=row["details"].get("seed_source"))
