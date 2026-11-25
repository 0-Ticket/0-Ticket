"""UI용 SQL. 테이블/열 이름은 코드 상수, 요청 값은 매개변수로만 전달한다."""

import re
from datetime import datetime
from typing import Any

from psycopg import sql

from soc.api.errors import InvalidQuery, NotFound
from soc.contracts import to_epoch_ms
from soc.contracts.alert import assemble_alert
from soc.contracts.event import assemble_event

UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
SEED_NAMES = ("dev-seed", "dev-seed-l1", "dev-seed-ui")
TICKET_SEVERITY = "(SELECT COALESCE(max(a.severity),0) FROM alerts a WHERE a.id = ANY(t.alert_ids))"
TICKET_COLUMNS = (
    f"t.id, t.title, t.origin, t.status, {TICKET_SEVERITY} AS severity, "
    "t.created_at, t.updated_at, "
    "t.details->>'seed_source' AS seed_source"
)
INCIDENT_COLUMNS = (
    "i.id, i.title, i.status, i.severity, i.assessed_severity, "
    "COALESCE(i.assessed_severity,i.severity) AS display_severity, i.analysis_round, "
    "i.updated_at, i.details->>'seed_source' AS seed_source"
)
TICKET_INCIDENT_KEYS = (
    "id",
    "title",
    "status",
    "severity",
    "assessed_severity",
    "display_severity",
)
CASE_COLUMNS = (
    "c.id, c.incident_id, c.title, c.severity, c.status, c.confirmed_at, "
    "c.details->>'seed_source' AS seed_source"
)


def check_id(value: str, prefixes: tuple[str, ...], *, cursor: bool = False) -> None:
    if not any(re.fullmatch(p + "_" + UUID7, value) for p in prefixes):
        if cursor:
            raise InvalidQuery("cursor")
        raise NotFound


def times(row: dict[str, Any]) -> dict[str, Any]:
    return {k: to_epoch_ms(v) if isinstance(v, datetime) else v for k, v in row.items()}


def page(rows: list[dict[str, Any]], limit: int, key: str = "id") -> dict[str, Any]:
    return {
        "items": [times(r) for r in rows[:limit]],
        "next_cursor": rows[limit - 1][key] if len(rows) > limit else None,
    }


def raw_query(kind: str) -> str:
    # Each raw row occurs once, including legacy seed rows without a status record.
    table = {"alert": "alerts", "event": "events"}[kind]
    title = "a.title" if kind == "alert" else "a.summary"
    projection = "id, title, severity" if kind == "alert" else "id, summary"
    severity = "a.severity" if kind == "alert" else "NULL::smallint"
    return f"""SELECT r.id AS raw_id, a.id AS record_id, r.fetched_at,
        {title} AS title, {severity} AS severity,
        CASE WHEN a.id IS NOT NULL THEN 'succeeded'
            ELSE COALESCE(n.status,'pending') END AS normalize_status,
        CASE WHEN a.id IS NULL THEN n.error_code END AS error_code,
        CASE WHEN r.siem_profile IN ('dev-seed','dev-seed-l1','dev-seed-ui')
            THEN r.siem_profile END AS seed_source
        FROM raw_records r
        LEFT JOIN LATERAL (SELECT {projection} FROM {table} a
            WHERE a.raw_id=r.id ORDER BY a.id DESC LIMIT 1) a ON true
        LEFT JOIN normalize_status n ON n.raw_id=r.id WHERE r.kind='{kind}'"""


def raw_page(conn, kind, status, cursor, limit):
    if cursor:
        check_id(cursor, ("raw",), cursor=True)
    where = []
    args = []
    for column, value, op in [("normalize_status", status, "="), ("raw_id", cursor, "<")]:
        if value is not None:
            where.append(f"{column} {op} %s")
            args.append(value)
    query = "SELECT * FROM (" + raw_query(kind) + ") q"
    if where:
        query += " WHERE " + " AND ".join(where)
    rows = conn.execute(query + " ORDER BY raw_id DESC LIMIT %s", [*args, limit + 1]).fetchall()
    return page(rows, limit, "raw_id")


def raw_detail(conn, kind, record_id):
    check_id(record_id, ("raw", "alt" if kind == "alert" else "evt"))
    item = conn.execute(
        "SELECT * FROM (" + raw_query(kind) + ") q WHERE raw_id=%s OR record_id=%s",
        (record_id, record_id),
    ).fetchone()
    if item is None:
        raise NotFound
    raw = conn.execute("SELECT * FROM raw_records WHERE id=%s", (item["raw_id"],)).fetchone()
    record = None
    if item["record_id"]:
        table = {"alert": "alerts", "event": "events"}[kind]
        record = conn.execute(
            sql.SQL("SELECT * FROM {} WHERE id=%s").format(sql.Identifier(table)),
            (item["record_id"],),
        ).fetchone()
    if record:  # Alert·Event는 OCSF 문서에 우리 값을 details로 합친 계약 모양이다(D-066, D-068)
        record = assemble_alert(record) if kind == "alert" else assemble_event(record)
    return dict(
        raw_record=times(raw),
        record=record or None,
        normalize_status=item["normalize_status"],
        error_code=item["error_code"],
        seed_source=item["seed_source"],
    )


def read_page(conn, table, columns, alias, filters, cursor, limit):
    prefixes = {"tickets": "tkt", "incidents": "inc", "cases": "cas"}
    if cursor:
        check_id(cursor, (prefixes[table],), cursor=True)
    where = []
    args = []
    for column, value in filters:
        if value is not None:
            where.append(f"{column} = %s")
            args.append(value)
    if cursor:
        where.append(f"{alias}.id < %s")
        args.append(cursor)
    query = f"SELECT {columns} FROM {table} {alias}"
    if where:
        query += " WHERE " + " AND ".join(where)
    rows = conn.execute(
        query + f" ORDER BY {alias}.id DESC LIMIT %s", [*args, limit + 1]
    ).fetchall()
    return page(rows, limit)


def detail(conn, table, prefix, record_id):
    check_id(record_id, (prefix,))
    row = conn.execute(
        sql.SQL("SELECT * FROM {} WHERE id=%s").format(sql.Identifier(table)), (record_id,)
    ).fetchone()
    if row is None:
        raise NotFound
    return times(row)


def alert_summaries(conn, alert_ids: list[str]) -> list[dict[str, Any]]:
    """Ticket의 원본 Alert 요약(#365). 쿼리 한 번이고 alert_ids 순서를 따른다. 없는 Alert는 뺀다."""
    if not alert_ids:
        return []
    rows = conn.execute(
        "SELECT id, title, time, severity FROM alerts WHERE id = ANY(%s)", (alert_ids,)
    ).fetchall()
    by_id = {row["id"]: times(row) for row in rows}
    return [by_id[i] for i in alert_ids if i in by_id]


def incident_alerts(conn, alert_ids: list[str]) -> list[dict[str, Any]]:
    """Incident의 Alert들(#376, #379). 쿼리 한 번이고 Alert 수와 관계없이 일정하다.

    시각(`time`), 엔티티와 자산 스냅샷(`assets`)을 읽는다. 시각 오름차순, 같으면 id 순이다.
    """
    if not alert_ids:
        return []
    rows = conn.execute(
        "SELECT id, time, entities, assets FROM alerts WHERE id = ANY(%s) ORDER BY time, id",
        (list(dict.fromkeys(alert_ids)),),
    ).fetchall()
    return [times(row) for row in rows]


def entity_criticality(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alert들의 자산 중요도를 (type, value)별 최댓값으로 모은다(#376). 키 순서로 준다.

    `alerts.assets`는 정규화 시점의 스냅샷이다. 중요도가 null인 자산은 건너뛴다.
    """
    best: dict[tuple[str, str], int] = {}
    for row in alerts:
        for asset in row["assets"]:
            level = asset["criticality"]
            if level is not None:
                key = (asset["entity"]["type"], asset["entity"]["value"])
                best[key] = max(level, best.get(key, level))
    return [{"type": k[0], "value": k[1], "criticality": v} for k, v in sorted(best.items())]


def ticket_incidents(conn, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Ticket id → 붙은 Incident 요약(#345). 연결의 원본은 incidents.ticket_ids다.

    여러 Incident에 붙어 있으면 id가 가장 큰(가장 최근) 하나만 준다. `&&`는 GIN 인덱스를 탄다.
    """
    if not ticket_ids:
        return {}
    wanted = set(ticket_ids)
    rows = conn.execute(
        f"SELECT {INCIDENT_COLUMNS}, i.ticket_ids FROM incidents i "
        "WHERE i.ticket_ids && %s::text[] ORDER BY i.id DESC",
        (ticket_ids,),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        summary = {key: row[key] for key in TICKET_INCIDENT_KEYS}
        for ticket_id in row["ticket_ids"]:
            if ticket_id in wanted:
                out.setdefault(ticket_id, summary)
    return out
