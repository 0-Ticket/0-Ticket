"""Incident 승인·반려 쓰기(#365, D-076, #375, D-082). 요청 값은 매개변수로만 전달한다.

Incident 행을 잠그고 awaiting_review일 때만 적용한다. 겹친 요청은 잠금 때문에 하나만 통과하고
나머지는 바뀐 상태를 보고 거절된다. 승인·반려는 같은 트랜잭션에서 review_round를 올리고
incident_reviews에 한 줄을 남긴다. 반려는 상태를 analyzing으로 돌리고 재분석은 기존 L2 분석
워커가 한다(사유는 그 워커가 incident_reviews에서 읽는다. 한도는 후속이다).
"""

from typing import Any

from psycopg.types.json import Jsonb

from soc.api import ui_read as read
from soc.api.errors import NotAwaitingReview, NotFound
from soc.ids import new_id


def _lock_awaiting(conn, incident_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, title, summary, entities, severity, assessed_severity, status, analysis_round "
        "FROM incidents WHERE id=%s FOR UPDATE",
        (incident_id,),
    ).fetchone()
    if row is None:
        raise NotFound
    if row["status"] != "awaiting_review":
        raise NotAwaitingReview(row["status"])
    return row


def _item(conn, incident_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {read.INCIDENT_COLUMNS} FROM incidents i WHERE i.id=%s", (incident_id,)
    ).fetchone()
    return read.times(row)


def _record(
    conn, row: dict[str, Any], decision: str, reason: str | None, username: str, status: str
) -> None:
    """상태를 바꾸고 review_round를 올린 뒤 그 값으로 검토 행을 남긴다. 트랜잭션 안에서 부른다."""
    review_round = conn.execute(
        "UPDATE incidents SET status=%s, review_round=review_round+1, updated_at=now() "
        "WHERE id=%s RETURNING review_round",
        (status, row["id"]),
    ).fetchone()["review_round"]
    conn.execute(
        "INSERT INTO incident_reviews (incident_id, decision, reason, decided_by, review_round, "
        "analysis_round) VALUES (%s, %s, %s, %s, %s, %s)",
        (row["id"], decision, reason, username, review_round, row["analysis_round"]),
    )


def approve_incident(conn, incident_id: str, username: str) -> dict[str, Any]:
    with conn.transaction():
        row = _lock_awaiting(conn, incident_id)
        case_id = new_id("cas")
        # 승인 시점 값을 그대로 복사한다. assessed_severity가 0이어도 그 값을 쓴다(None만 폴백)
        severity = row["severity"] if row["assessed_severity"] is None else row["assessed_severity"]
        conn.execute(
            "INSERT INTO cases (id, incident_id, title, summary, severity, entities, "
            "confirmed_by, confirmed_at, status, assignee, resolved_at, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, now(), 'open', NULL, NULL, '{}'::jsonb)",
            (
                case_id,
                incident_id,
                row["title"],
                row["summary"],
                severity,
                Jsonb(row["entities"]),
                username,
            ),
        )
        _record(conn, row, "approve", None, username, "confirmed")
        return {"incident": _item(conn, incident_id), "case_id": case_id}


def reject_incident(
    conn, incident_id: str, username: str, reason: str | None = None
) -> dict[str, Any]:
    with conn.transaction():
        row = _lock_awaiting(conn, incident_id)
        _record(conn, row, "reject", reason, username, "analyzing")
        return {"incident": _item(conn, incident_id), "case_id": None}
