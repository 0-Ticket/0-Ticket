"""승인 트랜잭션에서 Case 색인을 예약한다(#391). psycopg만 import한다."""

import psycopg


def enqueue(conn: psycopg.Connection, case_id: str) -> None:
    """Case를 만든 같은 트랜잭션에서 부른다. Case는 한 번만 색인하므로 이미 있으면 그대로 둔다."""
    conn.execute(
        "INSERT INTO case_index_jobs (case_id) VALUES (%s) ON CONFLICT (case_id) DO NOTHING",
        (case_id,),
    )
