"""Ticket별 대기 버전을 Qdrant 분류 색인에 반영한다."""

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

import psycopg

from soc.l2.branch.context import build_context
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.read import read_branch_data
from soc.l2.branch.runtime import BranchService, get_service
from soc.store import CollectionMissing
from soc.store.config import read_settings


def index_one(conn: psycopg.Connection, ticket_id: str, service: BranchService) -> bool:
    """세션 잠금으로 같은 Ticket의 Qdrant 쓰기를 직렬화한다."""
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 370))", (ticket_id,))
    revision = None
    try:
        row = conn.execute(
            "SELECT revision, indexed_revision FROM l2_ticket_index_jobs WHERE ticket_id = %s",
            (ticket_id,),
        ).fetchone()
        if row is None or row[0] <= row[1]:
            return False
        revision = row[0]
        context = build_context(read_branch_data(conn, ticket_id, expected_status=None))
        text = embedding_text(context)
        vector = service.embedder.embed(text)
        payload = {"linked": context.ticket["status"] == "linked", "revision": revision}
        try:
            service.store.upsert(ticket_id.removeprefix("tkt_"), vector, payload)
        except CollectionMissing:
            service.store.ensure_collection()
            service.store.upsert(ticket_id.removeprefix("tkt_"), vector, payload)
        conn.execute(
            """UPDATE l2_ticket_index_jobs SET indexed_revision = %s, failed_revision = NULL
            WHERE ticket_id = %s AND indexed_revision < %s""",
            (revision, ticket_id, revision),
        )
        return True
    except Exception:
        if revision is not None:
            conn.execute(
                """UPDATE l2_ticket_index_jobs SET failed_revision = %s, updated_at = now()
                WHERE ticket_id = %s AND revision = %s""",
                (revision, ticket_id, revision),
            )
        raise
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 370))", (ticket_id,))


@dataclass(frozen=True)
class L2IndexWorker:
    database_url: str
    settings: Any
    service: BranchService | None = None

    stage = "l2"
    name = "l2_ticket_index"

    def poll(self, limit: int) -> list[str]:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            rows = conn.execute(
                """SELECT ticket_id FROM l2_ticket_index_jobs
                WHERE revision > indexed_revision ORDER BY updated_at, ticket_id LIMIT %s""",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, ticket_id: str) -> None:
        service = self.service or get_service(self.settings)
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            index_one(conn, ticket_id, service)


def build_worker(config: dict[str, Any]) -> L2IndexWorker:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    return L2IndexWorker(database_url, read_settings(config["store"]))


def reindex(database_url: str, service: BranchService, *, recreate: bool = False) -> dict[str, int]:
    """모든 Ticket을 대기열에 다시 넣고 순차적으로 반영한다."""
    if recreate and service.store.exists():
        service.store.drop_collection()
    service.store.ensure_collection()
    counts = {"processed": 0, "succeeded": 0, "failed": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO l2_ticket_index_jobs (ticket_id)
            SELECT id FROM tickets WHERE true ON CONFLICT (ticket_id) DO UPDATE SET
            revision = l2_ticket_index_jobs.revision + 1,
            indexed_revision = 0, failed_revision = NULL, updated_at = now()"""
        )
        ids = [row[0] for row in conn.execute("SELECT id FROM tickets ORDER BY id").fetchall()]
        for ticket_id in ids:
            counts["processed"] += 1
            try:
                index_one(conn, ticket_id, service)
            except Exception:
                counts["failed"] += 1
            else:
                counts["succeeded"] += 1
    return counts


def check(database_url: str, service: BranchService) -> dict[str, int]:
    """PostgreSQL Ticket과 Qdrant point의 버전·상태를 전수 대조한다."""
    counts = {"tickets": 0, "missing": 0, "stale": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """SELECT t.id, t.status, j.revision, j.indexed_revision
            FROM tickets t LEFT JOIN l2_ticket_index_jobs j ON j.ticket_id = t.id"""
        ).fetchall()
        for ticket_id, status, revision, indexed in rows:
            counts["tickets"] += 1
            payload = service.store.point_payload(ticket_id.removeprefix("tkt_"))
            if payload is None:
                counts["missing"] += 1
            elif (
                revision is None
                or indexed != revision
                or payload.get("revision") != revision
                or payload.get("linked") is not (status == "linked")
            ):
                counts["stale"] += 1
    return counts


def resume(database_url: str, ticket_id: str) -> bool:
    """L2 분류 오류로 보류된 Ticket 하나만 재개한다."""
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """UPDATE tickets SET status = 'escalated',
            details = jsonb_set(details, '{l2_branch}',
                (details->'l2_branch') - 'next_retry_at' - 'progress' - 'held_by'
                || '{"failures": 0}'::jsonb)
            WHERE id = %s AND status = 'held'
              AND details->'l2_branch'->>'held_by' = 'l2_branch'
            RETURNING id""",
            (ticket_id,),
        ).fetchone()
    return row is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="L2 Ticket 분류 색인 관리")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    reindex_cmd = sub.add_parser("reindex")
    reindex_cmd.add_argument("--recreate", action="store_true")
    sub.add_parser("resume").add_argument("ticket_id")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL이 필요하다")
    try:
        if args.command == "resume":
            print("resumed" if resume(database_url, args.ticket_id) else "not_l2_held")
            return 0
        from soc.store.config import load_config

        service = get_service(read_settings(load_config()["store"]))
        result = (
            check(database_url, service)
            if args.command == "check"
            else reindex(database_url, service, recreate=args.recreate)
        )
    except Exception as exc:
        print(f"분류 색인 명령 실패({type(exc).__name__})", file=sys.stderr)
        return 1
    print(result)
    return 1 if any(result.get(key, 0) for key in ("missing", "stale", "failed")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
