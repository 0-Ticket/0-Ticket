"""UI용 SQL. 테이블/열 이름은 코드 상수, 요청 값은 매개변수로만 전달한다."""

import re
from datetime import datetime
from typing import Any

from psycopg import sql

from soc.api.errors import InvalidQuery, NotFound
from soc.contracts import to_epoch_ms

UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
SEED_NAMES = ("dev-seed", "dev-seed-l1", "dev-seed-ui")
TICKET_SEVERITY = "(SELECT COALESCE(max(a.severity),0) FROM alerts a WHERE a.id = ANY(t.alert_ids))"
TICKET_COLUMNS = (
    f"t.id, t.origin, t.status, {TICKET_SEVERITY} AS severity, t.created_at, t.updated_at, "
    "t.details->>'seed_source' AS seed_source"
)
INCIDENT_COLUMNS = (
    "i.id, i.title, i.status, i.severity, i.assessed_severity, "
    "COALESCE(i.assessed_severity,i.severity) AS display_severity, i.analysis_round, "
    "i.updated_at, i.details->>'seed_source' AS seed_source"
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
    return dict(
        raw_record=times(raw),
        record=times(record) if record else None,
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
