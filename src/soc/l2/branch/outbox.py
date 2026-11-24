"""Ticket 변경과 같은 PostgreSQL 트랜잭션에서 분류 색인을 예약한다."""

import psycopg


def enqueue(conn: psycopg.Connection, ticket_id: str) -> None:
    conn.execute(
        """INSERT INTO l2_ticket_index_jobs (ticket_id) VALUES (%s)
        ON CONFLICT (ticket_id) DO UPDATE SET
            revision = l2_ticket_index_jobs.revision + 1,
            failed_revision = NULL,
            updated_at = now()""",
        (ticket_id,),
    )
