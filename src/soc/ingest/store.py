"""수집한 페이지를 raw_records(0001)와 ingest_checkpoints(0100)에 쓴다.

페이지의 원본과 다음 위치(체크포인트)는 트랜잭션 하나로 함께 커밋하거나 함께 되돌린다.
그래서 체크포인트는 늘 마지막으로 저장에 성공한 페이지를 가리킨다.
"""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms, validate_contract

# 같은 (siem_profile, siem_ref)가 이미 있으면 처음 저장한 원본을 그대로 둔다
_INSERT_RAW = """
INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original)
VALUES (%(id)s, %(kind)s, %(siem_profile)s, %(siem_ref)s, %(fetched_at)s, %(original)s)
ON CONFLICT (siem_profile, siem_ref) DO NOTHING
"""

_UPSERT_CHECKPOINT = """
INSERT INTO ingest_checkpoints
    (siem_profile, source_kind, source_key, cursor, updated_at, last_error)
VALUES (%(siem_profile)s, %(source_kind)s, %(source_key)s, %(cursor)s, %(updated_at)s,
        %(last_error)s)
ON CONFLICT (siem_profile, source_kind, source_key) DO UPDATE SET
    cursor = EXCLUDED.cursor,
    updated_at = EXCLUDED.updated_at,
    last_error = EXCLUDED.last_error
"""


def load_checkpoint(
    conn: psycopg.Connection, siem_profile: str, source_kind: str, source_key: str
) -> dict[str, Any] | None:
    """ingest_checkpoint 계약 모양의 dict. 아직 저장한 적이 없으면 None."""
    row = conn.execute(
        "SELECT cursor, updated_at, last_error FROM ingest_checkpoints"
        " WHERE siem_profile = %s AND source_kind = %s AND source_key = %s",
        (siem_profile, source_kind, source_key),
    ).fetchone()
    if row is None:
        return None
    cursor, updated_at, last_error = row
    return {
        "siem_profile": siem_profile,
        "source_kind": source_kind,
        "source_key": source_key,
        "cursor": cursor,
        "updated_at": to_epoch_ms(updated_at),
        "last_error": last_error,
    }


def save_page(
    conn: psycopg.Connection, records: list[dict[str, Any]], checkpoint: dict[str, Any]
) -> int:
    """페이지의 원본과 체크포인트를 한 트랜잭션으로 쓰고, 새로 저장한 원본 수를 돌려준다.

    쓰기 전에 모든 원본(raw_record)과 체크포인트(ingest_checkpoint)를 계약으로 검사한다. 하나라도
    맞지 않으면 ContractError를 내고 아무것도 쓰지 않는다. DB 오류가 나면 둘 다 되돌리고 그 예외를
    그대로 낸다. 체크포인트의 last_error는 받은 값(성공이면 None)으로 덮어쓴다.
    """
    for record in records:
        validate_contract("raw_record", record)
    validate_contract("ingest_checkpoint", checkpoint)

    inserted = 0
    # autocommit 연결에서도 트랜잭션을 열고, 이미 열린 트랜잭션 안에서는 savepoint가 된다
    with conn.transaction():
        for record in records:
            cur = conn.execute(
                _INSERT_RAW,
                {
                    **record,
                    "fetched_at": to_datetime(record["fetched_at"]),
                    "original": Jsonb(record["original"]),
                },
            )
            inserted += cur.rowcount
        conn.execute(
            _UPSERT_CHECKPOINT,
            {
                **checkpoint,
                "cursor": Jsonb(checkpoint["cursor"]),
                "updated_at": to_datetime(checkpoint["updated_at"]),
            },
        )
    return inserted


def record_failure(
    conn: psycopg.Connection,
    siem_profile: str,
    source_kind: str,
    source_key: str,
    error_kind: str,
    now_ms: int,
) -> None:
    """실패 원인의 종류 코드를 남긴다. 이미 있는 cursor는 그대로 둔다.

    체크포인트가 아직 없으면(첫 페이지부터 실패) 빈 cursor로 행을 만든다. 빈 cursor는 "아직 성공한
    페이지가 없다"는 뜻이라 다음 실행은 처음부터 조회한다. error_kind는 원문이 아닌 코드여야 하며,
    테이블의 CHECK가 코드 모양이 아니면 거부한다.
    """
    conn.execute(
        "INSERT INTO ingest_checkpoints"
        " (siem_profile, source_kind, source_key, cursor, updated_at, last_error)"
        " VALUES (%s, %s, %s, '{}'::jsonb, %s, %s)"
        " ON CONFLICT (siem_profile, source_kind, source_key)"
        " DO UPDATE SET last_error = EXCLUDED.last_error, updated_at = EXCLUDED.updated_at",
        (siem_profile, source_kind, source_key, to_datetime(now_ms), error_kind),
    )
