"""정규화 상태 테이블(normalize_status)과 결과 저장.

원본 한 건을 한 번만 처리하도록 상태 행의 기본 키와 잠금, 임대로 막는다.
시각 비교는 모두 DB의 now()를 쓴다. SQL은 매개변수로만 값을 넣는다.
"""

from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime
from soc.normalize.mapping import RawRow

_TABLES = {"alert": "alerts", "event": "events"}
_COLUMNS = {
    "alert": (
        "id",
        "raw_id",
        "time",
        "severity",
        "title",
        "rule_id",
        "entities",
        "assets",
        "triage",
        "ocsf",
        "details",
    ),
    "event": (
        "id",
        "raw_id",
        "time",
        "ocsf_class",
        "summary",
        "entities",
        "assets",
        "ocsf",
        "details",
    ),
}
_JSON_COLUMNS = {"entities", "assets", "triage", "ocsf", "details"}

_ADD_STATUS_ROWS = """
INSERT INTO normalize_status (raw_id)
SELECT r.id FROM raw_records r
WHERE NOT EXISTS (SELECT 1 FROM normalize_status s WHERE s.raw_id = r.id)
ORDER BY r.id
LIMIT %s
ON CONFLICT (raw_id) DO NOTHING
"""

_LEASE = """
UPDATE normalize_status
SET lease_owner = %s, lease_expires_at = now() + make_interval(secs => %s), last_attempt_at = now()
WHERE raw_id IN (
    SELECT raw_id FROM normalize_status
    WHERE status <> 'succeeded' AND (lease_expires_at IS NULL OR lease_expires_at < now())
    ORDER BY last_attempt_at NULLS FIRST, raw_id
    LIMIT %s
    FOR UPDATE SKIP LOCKED
)
RETURNING raw_id
"""

_LOCK_HELD = """
SELECT 1 FROM normalize_status
WHERE raw_id = %s AND lease_owner = %s AND lease_expires_at > now() AND status <> 'succeeded'
FOR UPDATE
"""

_MARK_SUCCEEDED = """
UPDATE normalize_status
SET status = 'succeeded', error_code = NULL, attempts = attempts + 1, last_attempt_at = now(),
    result_kind = %s, result_id = %s, lease_owner = NULL, lease_expires_at = NULL
WHERE raw_id = %s
"""

_MARK_FAILED = """
UPDATE normalize_status
SET status = 'failed', error_code = %s, attempts = attempts + 1, last_attempt_at = now(),
    lease_owner = NULL, lease_expires_at = NULL
WHERE raw_id = %s AND lease_owner = %s AND lease_expires_at > now() AND status <> 'succeeded'
"""


def claim_batch(
    conn: psycopg.Connection, owner: str, batch_size: int, lease_seconds: int
) -> list[RawRow]:
    """처리할 원본을 최대 batch_size건 임대해 읽어 온다.

    아직 상태 행이 없는 원본에 행을 만든 뒤, 성공하지 않았고 임대가 없거나 만료된 행을
    시도한 지 오래된 순서로 잡는다. 다른 작업자가 잠근 행은 건너뛴다.

    Args:
        conn: 쓰기 연결(autocommit).
        owner: 이번 실행을 가리키는 임대 소유자 값.
        batch_size: 한 번에 잡을 최대 건수.
        lease_seconds: 임대 시간(초).
    """
    conn.execute(_ADD_STATUS_ROWS, (batch_size,))
    claimed = conn.execute(_LEASE, (owner, lease_seconds, batch_size)).fetchall()
    ids = [row[0] for row in claimed]
    rows = conn.execute(
        "SELECT id, kind, original FROM raw_records WHERE id = ANY(%s) ORDER BY id", (ids,)
    ).fetchall()
    return [RawRow(id=row[0], kind=row[1], original=row[2]) for row in rows]


def save_success(
    conn: psycopg.Connection, owner: str, raw_id: str, kind: str, row: dict[str, Any]
) -> bool:
    """결과 행을 저장하고 상태를 성공으로 바꾼다. 한 트랜잭션이다.

    임대를 아직 가지고 있을 때만 쓴다. 임대를 잃었으면 아무것도 쓰지 않는다.

    Args:
        conn: 쓰기 연결(autocommit).
        owner: 이번 실행의 임대 소유자 값.
        raw_id: 정규화한 원본의 raw_records.id.
        kind: 결과 종류. "alert" 또는 "event".
        row: 계약 검증을 통과한 alerts 또는 events 행.

    Returns:
        저장했으면 True, 임대를 잃어 저장하지 않았으면 False.
    """
    with conn.transaction():
        if conn.execute(_LOCK_HELD, (raw_id, owner)).fetchone() is None:
            return False
        _insert_result(conn, kind, row)
        conn.execute(_MARK_SUCCEEDED, (kind, row["id"], raw_id))
    return True


def save_failure(conn: psycopg.Connection, owner: str, raw_id: str, code: str) -> bool:
    """상태를 실패로 바꾸고 임대를 푼다. 원문 예외는 저장하지 않는다.

    Args:
        conn: 쓰기 연결(autocommit).
        owner: 이번 실행의 임대 소유자 값.
        raw_id: 실패한 원본의 raw_records.id.
        code: 실패 코드(errors.FAILURES 중 하나).

    Returns:
        기록했으면 True, 임대를 잃어 기록하지 않았으면 False.
    """
    return conn.execute(_MARK_FAILED, (code, raw_id, owner)).rowcount == 1


def _insert_result(conn: psycopg.Connection, kind: str, row: dict[str, Any]) -> None:
    """alerts 또는 events에 결과 행 하나를 넣는다.

    Args:
        conn: 열린 트랜잭션 안의 연결.
        kind: 결과 종류. "alert" 또는 "event".
        row: 계약 모양의 행. time은 epoch 밀리초, JSON 칸은 dict나 list.
    """
    columns = _COLUMNS[kind]
    values = [_db_value(column, row[column]) for column in columns]
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(_TABLES[kind]),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() * len(columns)),
    )
    conn.execute(query, values)


def _db_value(column: str, value: Any) -> Any:
    """계약 값을 DB 값으로 바꾼다. 시각은 datetime, JSON 칸은 Jsonb, null은 SQL NULL.

    Args:
        column: 칸 이름.
        value: 계약 모양의 값.
    """
    if column == "time":
        return to_datetime(value)
    if column in _JSON_COLUMNS and value is not None:
        return Jsonb(value)
    return value
