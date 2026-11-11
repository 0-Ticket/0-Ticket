"""수집한 페이지를 raw_records(0001)와 ingest_checkpoints(0100)에 쓴다.

페이지의 원본과 다음 위치(체크포인트)는 트랜잭션 하나로 함께 커밋하거나 함께 되돌린다.
그래서 체크포인트는 늘 마지막으로 저장에 성공한 페이지를 가리킨다.
실행 이력은 그와 따로 ingest_runs(0101)에 실행마다 한 행씩 쌓는다.
"""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms, validate_contract

# 같은 (siem_profile, siem_ref)가 이미 있으면 처음 저장한 원본을 그대로 둔다
_INSERT_RAW = """
INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)
VALUES (%(id)s, %(kind)s, %(siem_profile)s, %(siem_ref)s, %(fetched_at)s, %(original_text)s)
ON CONFLICT (siem_profile, siem_ref) DO NOTHING
"""

_UPSERT_CHECKPOINT = """
INSERT INTO ingest_checkpoints (siem_profile, source_kind, source_key, cursor, updated_at)
VALUES (%(siem_profile)s, %(source_kind)s, %(source_key)s, %(cursor)s, %(updated_at)s)
ON CONFLICT (siem_profile, source_kind, source_key) DO UPDATE SET
    cursor = EXCLUDED.cursor,
    updated_at = EXCLUDED.updated_at
"""

_INSERT_RUN = """
INSERT INTO ingest_runs
    (siem_profile, source_kind, source_key, started_at, finished_at, outcome, pages, inserted)
VALUES (%(siem_profile)s, %(source_kind)s, %(source_key)s, %(started_at)s, %(finished_at)s,
        %(outcome)s, %(pages)s, %(inserted)s)
"""


def load_checkpoint(
    conn: psycopg.Connection, siem_profile: str, source_kind: str, source_key: str
) -> dict[str, Any] | None:
    """체크포인트 한 행을 읽는다.

    인자:
        conn: 연결(autocommit이 아니어도 된다. 읽기만 한다).
        siem_profile: 체크포인트의 프로필 이름.
        source_kind: "alert" 또는 "event".
        source_key: 조회 대상(Source.key).

    반환:
        ingest_checkpoint 계약 모양의 dict(siem_profile, source_kind, source_key,
        cursor, updated_at(epoch ms)). 행이 없으면 None.
    """
    row = conn.execute(
        "SELECT cursor, updated_at FROM ingest_checkpoints"
        " WHERE siem_profile = %s AND source_kind = %s AND source_key = %s",
        (siem_profile, source_kind, source_key),
    ).fetchone()
    if row is None:
        return None
    cursor, updated_at = row
    return {
        "siem_profile": siem_profile,
        "source_kind": source_kind,
        "source_key": source_key,
        "cursor": cursor,
        "updated_at": to_epoch_ms(updated_at),
    }


def save_page(
    conn: psycopg.Connection, records: list[dict[str, Any]], checkpoint: dict[str, Any]
) -> int:
    """페이지의 원본과 체크포인트를 한 트랜잭션으로 쓰고, 새로 저장한 원본 수를 돌려준다.

    인자:
        conn: autocommit 연결. 이 함수가 트랜잭션을 연다.
        records: 한 페이지의 RawRecord dict 목록. 비어 있을 수 있다.
        checkpoint: 이 페이지를 끝낸 뒤의 ingest_checkpoint dict. cursor는 다음 조회 위치다.

    쓰기 전에 모든 원본(raw_record)과 체크포인트(ingest_checkpoint)를 계약으로 검사한다. 하나라도
    맞지 않으면 ContractError를 내고 아무것도 쓰지 않는다. DB 오류가 나면 둘 다 되돌리고 그 예외를
    그대로 낸다.
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


def record_run(conn: psycopg.Connection, run: dict[str, Any]) -> None:
    """조회 대상 하나의 실행 이력 한 행을 쌓는다. 원본·체크포인트와는 다른 트랜잭션이다.

    인자:
        conn: autocommit 연결. INSERT 한 번이 바로 커밋된다.
        run: ingest_run 계약 모양의 dict. started_at·finished_at은 epoch ms, outcome은 "ok" 또는
            FAILURES 중 하나의 코드다.

    쓰기 전에 계약으로 검사하고, 맞지 않으면 ContractError를 내고 쓰지 않는다.
    DB 오류는 그대로 낸다.
    """
    validate_contract("ingest_run", run)
    conn.execute(
        _INSERT_RUN,
        {
            **run,
            "started_at": to_datetime(run["started_at"]),
            "finished_at": to_datetime(run["finished_at"]),
        },
    )


# 같은 쌍을 두 번 넣어도 오류가 나지 않게 한다(재시도 때 안전)
_INSERT_LINK = """
INSERT INTO raw_links (raw_id, source_raw_id)
VALUES (%s, %s)
ON CONFLICT (raw_id, source_raw_id) DO NOTHING
"""

_FIND_RAW_ID = """
SELECT id FROM raw_records WHERE siem_profile = %s AND kind = %s AND siem_ref = %s
"""


def link_by_refs(
    conn: psycopg.Connection, siem_profile: str, pairs: list[tuple[str, str]]
) -> tuple[int, list[tuple[str, str]]]:
    """알럿과 이벤트를 siem_ref 쌍으로 받아 raw_links에 한 트랜잭션으로 연결한다.

    한쪽 원본이 아직 저장되지 않은 쌍은 연결하지 않고 돌려준다. 호출한 쪽이 나중에 다시 넘긴다.

    인자:
        conn: autocommit 연결. 이 함수가 트랜잭션을 연다.
        siem_profile: 두 원본이 속한 SIEM 프로필 이름.
        pairs: (알럿 siem_ref, 이벤트 siem_ref) 목록. siem_ref는 "<_index>/<_id>"다.

    반환:
        (새로 저장한 연결 수, 원본이 없어 보류한 쌍). 이미 연결된 쌍은 세지 않고 보류하지도 않는다.
    """
    linked = 0
    pending: list[tuple[str, str]] = []
    with conn.transaction():
        for alert_ref, event_ref in pairs:
            alert = conn.execute(_FIND_RAW_ID, (siem_profile, "alert", alert_ref)).fetchone()
            event = conn.execute(_FIND_RAW_ID, (siem_profile, "event", event_ref)).fetchone()
            if alert is None or event is None:
                pending.append((alert_ref, event_ref))
                continue
            linked += conn.execute(_INSERT_LINK, (alert[0], event[0])).rowcount
    return linked, pending
