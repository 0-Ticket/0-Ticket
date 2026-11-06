"""헌팅이 읽고 쓰는 SQL. Hunt·Ticket은 계약 모양(시각은 epoch ms)으로 주고받는다.

쓰는 쪽(가설 생성·검증)이 validate_contract()를 먼저 거치고, 트랜잭션도 쓰는 쪽이 연다.
Hunt 상태 규칙은 DB가 막지 않는다(0002 헤더).
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms

_HUNT_COLUMNS = (
    "id",
    "hunt_run_id",
    "status",
    "hypothesis",
    "attack_techniques",
    "confidence",
    "reason",
    "evidence_ids",
    "entities",
    "attempts",
    "verified_at",
    "created_at",
    "updated_at",
    "details",
)
_HUNT_TIMES = ("verified_at", "created_at", "updated_at")
_HUNT_JSONB = ("entities", "details")

_TICKET_COLUMNS = (
    "id",
    "origin",
    "status",
    "alert_ids",
    "hunt_id",
    "entities",
    "verdict",
    "created_at",
    "updated_at",
    "details",
)


def _db_value(column: str, value: Any, times: Sequence[str], jsonb: Sequence[str]) -> Any:
    if value is None:
        return None  # null이 될 수 있는 jsonb 칸(verdict)은 SQL NULL로 넣는다(0001 헤더)
    if column in times:
        return to_datetime(value)
    if column in jsonb:
        return Jsonb(value)
    return value


def attack_names(conn: psycopg.Connection, version: str) -> dict[str, str]:
    """설정 버전의 ATT&CK 기법 ID → 이름."""
    rows = conn.execute(
        "SELECT technique_id, name FROM attack_techniques WHERE attack_version = %s", (version,)
    ).fetchall()
    return dict(rows)


def recent_news(conn: psycopg.Connection, *, since: datetime, limit: int) -> list[dict[str, Any]]:
    """발행 시각(없으면 처음 받은 시각)이 since 이후인 뉴스. 최근 것부터."""
    rows = conn.execute(
        "SELECT id, source, title, summary, published_at FROM threat_news"
        " WHERE COALESCE(published_at, fetched_at) >= %s"
        " ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT %s",
        (since, limit),
    ).fetchall()
    return [
        {
            "id": row[0],
            "source": row[1],
            "title": row[2],
            "summary": row[3],
            "published_at": None if row[4] is None else to_epoch_ms(row[4]),
        }
        for row in rows
    ]


def recent_cases(conn: psycopg.Connection, *, limit: int) -> list[dict[str, Any]]:
    """confirmed_at이 최근인 Case. Case는 정의상 사람이 확정한 것이라 상태는 보지 않는다."""
    rows = conn.execute(
        "SELECT id, title, summary, severity, entities FROM cases"
        " ORDER BY confirmed_at DESC, id DESC LIMIT %s",
        (limit,),
    ).fetchall()
    keys = ("id", "title", "summary", "severity", "entities")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def insert_hunts(conn: psycopg.Connection, hunts: Iterable[dict[str, Any]]) -> None:
    query = (
        f"INSERT INTO hunts ({', '.join(_HUNT_COLUMNS)})"  # 컬럼 이름은 상수다
        f" VALUES ({', '.join(['%s'] * len(_HUNT_COLUMNS))})"
    )
    with conn.cursor() as cur:
        cur.executemany(
            query,
            [[_db_value(c, h[c], _HUNT_TIMES, _HUNT_JSONB) for c in _HUNT_COLUMNS] for h in hunts],
        )


def read_hunt(conn: psycopg.Connection, hunt_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_HUNT_COLUMNS)} FROM hunts WHERE id = %s",  # 컬럼 이름은 상수다
        (hunt_id,),
    ).fetchone()
    if row is None:
        return None
    hunt = dict(zip(_HUNT_COLUMNS, row, strict=True))
    for column in _HUNT_TIMES:
        if hunt[column] is not None:
            hunt[column] = to_epoch_ms(hunt[column])
    return hunt


def pending_hunt_ids(conn: psycopg.Connection, limit: int | None) -> list[str]:
    """pending Hunt ID. 오래된 것부터. limit이 None이면 전부(LIMIT NULL)."""
    rows = conn.execute(
        "SELECT id FROM hunts WHERE status = 'pending' ORDER BY created_at, id LIMIT %s", (limit,)
    ).fetchall()
    return [row[0] for row in rows]


def update_hunt(conn: psycopg.Connection, hunt: dict[str, Any], *, read_attempts: int) -> bool:
    """읽은 뒤 다른 실행이 바꾸지 않았을 때만(pending, 같은 attempts) 갱신한다. 갱신했으면 True."""
    columns = [c for c in _HUNT_COLUMNS if c not in ("id", "hunt_run_id", "created_at")]
    assignments = ", ".join(f"{c} = %s" for c in columns)  # 컬럼 이름은 상수다
    row = conn.execute(
        f"UPDATE hunts SET {assignments}"
        " WHERE id = %s AND status = 'pending' AND attempts = %s RETURNING id",
        [
            *(_db_value(c, hunt[c], _HUNT_TIMES, _HUNT_JSONB) for c in columns),
            hunt["id"],
            read_attempts,
        ],
    ).fetchone()
    return row is not None


def record_entities(
    conn: psycopg.Connection, evidence_ids: Sequence[str]
) -> tuple[list[dict[str, Any]], int]:
    """근거 ID 중 alt_·evt_가 가리키는 Alert·Event의 엔티티(근거 순서대로)와, 행이 없는 ID 수."""
    alert_ids = [i for i in evidence_ids if i.startswith("alt_")]
    event_ids = [i for i in evidence_ids if i.startswith("evt_")]
    found: dict[str, list[dict[str, Any]]] = {}
    for table, ids in (("alerts", alert_ids), ("events", event_ids)):
        if ids:
            rows = conn.execute(
                f"SELECT id, entities FROM {table} WHERE id = ANY(%s)",  # 테이블 이름은 상수다
                (ids,),
            ).fetchall()
            found.update(dict(rows))
    entities = [e for i in evidence_ids if i in found for e in found[i]]
    missing = sum(1 for i in [*alert_ids, *event_ids] if i not in found)
    return entities, missing


def insert_ticket(conn: psycopg.Connection, ticket: dict[str, Any]) -> bool:
    """savepoint 안에서 넣는다. 같은 Hunt의 Ticket이 이미 있으면(tickets_hunt_id_key) False.

    호출하는 쪽의 트랜잭션 안에서 부른다. UniqueViolation을 savepoint로 되돌려 바깥 트랜잭션
    (Hunt 갱신)은 그대로 둔다.
    """
    query = (
        f"INSERT INTO tickets ({', '.join(_TICKET_COLUMNS)})"  # 컬럼 이름은 상수다
        f" VALUES ({', '.join(['%s'] * len(_TICKET_COLUMNS))})"
    )
    values = [
        _db_value(c, ticket[c], ("created_at", "updated_at"), ("entities", "verdict", "details"))
        for c in _TICKET_COLUMNS
    ]
    try:
        with conn.transaction():
            conn.execute(query, values)
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != "tickets_hunt_id_key":
            raise
        return False
    return True


def last_attempt_started_at(conn: psycopg.Connection, task: str) -> datetime | None:
    """L3 작업(task)의 마지막 시도 시각: 그 작업 Agent Log 줄의 가장 늦은 started_at.

    같은 run에 failure = cancelled인 줄이 있는 run은 뺀다(종료로 끊긴 run은 시도로 세지 않는다,
    #245). task는 칼럼이 아니라 details에 있고 인덱스가 없어 표 전체를 읽는다.
    """
    row = conn.execute(
        "SELECT max(l.started_at) FROM agent_logs l"
        " WHERE l.stage = 'l3' AND l.details->>'task' = %s"
        " AND NOT EXISTS (SELECT 1 FROM agent_logs c"
        " WHERE c.run_id = l.run_id AND c.details->>'failure' = 'cancelled')",
        (task,),
    ).fetchone()
    return None if row is None else row[0]


def status_counts(conn: psycopg.Connection, hunt_ids: Sequence[str]) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, count(*) FROM hunts WHERE id = ANY(%s) GROUP BY status", (list(hunt_ids),)
    ).fetchall()
    return dict(rows)
