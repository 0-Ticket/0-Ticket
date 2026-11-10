"""전체 보관 자료 집계. 한 읽기 전용 REPEATABLE READ 스냅샷에서 계산한다."""

from typing import get_args

from fastapi import APIRouter, Depends, Request

from soc.api import db
from soc.api import ui_read as read
from soc.api.auth import require_permission
from soc.api.models import HuntStatus
from soc.api.ui_models import CaseStatus, Dashboard, IncidentStatus, TicketStatus

router = APIRouter()


def _counts(conn, table, status_type):
    counts = {s: 0 for s in get_args(status_type)}
    for r in conn.execute(f"SELECT status,count(*) AS n FROM {table} GROUP BY status"):
        counts[r["status"]] = r["n"]
    return counts


@router.get(
    "/dashboard",
    response_model=Dashboard,
    dependencies=[Depends(require_permission("dashboard.read"))],
)
def dashboard(request: Request):
    with db.connect(request.app.state.settings) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        normalization = {}
        for kind in ("alert", "event"):
            counts = {"succeeded": 0, "failed": 0, "pending": 0}
            query = (
                "SELECT normalize_status,count(*) AS n FROM ("
                + read.raw_query(kind)
                + ") q GROUP BY normalize_status"
            )
            for r in conn.execute(query):
                counts[r["normalize_status"]] = r["n"]
            done = counts["succeeded"] + counts["failed"]
            normalization[kind] = {
                **counts,
                "success_ratio": counts["succeeded"] / done if done else None,
            }
        ticket_status = _counts(conn, "tickets", TicketStatus)
        incident_status = _counts(conn, "incidents", IncidentStatus)
        case_status = _counts(conn, "cases", CaseStatus)
        hunt_status = _counts(conn, "hunts", HuntStatus)
        severities = {str(i): 0 for i in range(7)}
        for r in conn.execute(
            f"SELECT {read.TICKET_SEVERITY} AS severity,count(*) AS n FROM tickets t GROUP BY 1"
        ):
            severities[str(r["severity"])] = r["n"]
        pending = conn.execute(
            "SELECT count(*) AS n FROM alerts WHERE triage->>'status'='pending'"
        ).fetchone()["n"]
        promoted = conn.execute(
            "SELECT count(*) AS n FROM hunts h WHERE EXISTS "
            "(SELECT 1 FROM tickets t WHERE t.hunt_id=h.id)"
        ).fetchone()["n"]
        top = conn.execute(
            f"SELECT {read.INCIDENT_COLUMNS} FROM incidents i "
            "WHERE status IN ('analyzing','awaiting_review','human_handling') "
            "ORDER BY display_severity DESC,i.id DESC LIMIT 10"
        ).fetchall()
        analyzed = conn.execute(
            f"SELECT {read.INCIDENT_COLUMNS} FROM incidents i WHERE EXISTS "
            "(SELECT 1 FROM incident_artifacts a WHERE a.incident_id=i.id) "
            "ORDER BY i.id DESC LIMIT 10"
        ).fetchall()
    total = sum(hunt_status.values())
    return dict(
        flow={
            "normalization_pending": sum(x["pending"] for x in normalization.values()),
            "l1_alerts_pending": pending,
            "l1_tickets_pending": ticket_status["new"],
            "tickets": sum(ticket_status.values()),
            "incidents": sum(incident_status.values()),
            "cases": sum(case_status.values()),
        },
        ticket_status=ticket_status,
        incident_status=incident_status,
        case_status=case_status,
        ticket_severity=severities,
        normalization=normalization,
        hunting=dict(
            statuses=hunt_status,
            total=total,
            promoted=promoted,
            promotion_ratio=promoted / total if total else None,
        ),
        top_incidents=[read.times(x) for x in top],
        analyzed_incidents=[read.times(x) for x in analyzed],
    )
