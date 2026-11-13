"""판정이 끝난 Ticket을 유사 사례 컬렉션(`ticket_verdicts`)에 색인한다(#313, D-053).

point ID는 Ticket ID에서 `tkt_`를 뗀 UUID이고 payload는 비운다. 상태·판정·시각은 검색할 때
PostgreSQL에서 읽는다(권위 원본, D-013). Qdrant 쓰기는 PostgreSQL 트랜잭션에 묶지 않는다.
"""

import logging
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from soc.similar.text import similar_text
from soc.store import CollectionMissing, Embedder, VectorStore

PURPOSE = "ticket_verdicts"
logger = logging.getLogger("soc.similar")


def ticket_text(conn: psycopg.Connection, ticket_id: str) -> str | None:
    """판정이 있는 Ticket의 색인 텍스트. Ticket이 없거나 판정이 없으면 None."""
    with conn.cursor(row_factory=tuple_row) as cur:
        row = cur.execute(
            "SELECT verdict IS NOT NULL, origin, alert_ids, hunt_id FROM tickets WHERE id = %s",
            (ticket_id,),
        ).fetchone()
        if row is None or not row[0]:
            return None
        _, origin, alert_ids, hunt_id = row
        found = dict(
            cur.execute(
                "SELECT id, title FROM alerts WHERE id = ANY(%s)", (list(alert_ids),)
            ).fetchall()
        )
        hypothesis = None
        if origin == "l3" and hunt_id:
            hunt = cur.execute("SELECT hypothesis FROM hunts WHERE id = %s", (hunt_id,)).fetchone()
            hypothesis = None if hunt is None else hunt[0]
    return similar_text([found[a] for a in alert_ids if a in found], hypothesis)


def upsert_ticket(ticket_id: str, text: str, embedder: Embedder, store: VectorStore) -> None:
    """텍스트를 임베딩해 point 하나를 넣는다. 컬렉션이 없으면 한 번 만들고 다시 넣는다."""
    vector = embedder.embed(text)
    point_id = ticket_id.removeprefix("tkt_")
    try:
        store.upsert(point_id, vector, {})
    except CollectionMissing:
        store.ensure_collection()
        store.upsert(point_id, vector, {})


def index_ticket(
    conn: psycopg.Connection, ticket_id: str, embedder: Embedder, store: VectorStore
) -> bool:
    """판정이 있는 Ticket 하나를 색인한다. 색인했으면 True, 판정·텍스트가 없어 건너뛰면 False.

    발생:
        StoreError: Qdrant 쓰기가 실패했을 때. 부르는 쪽이 잡는다.
    """
    text = ticket_text(conn, ticket_id)
    if not text:
        return False
    upsert_ticket(ticket_id, text, embedder, store)
    return True


def reindex(
    database_url: str,
    embedder: Embedder,
    store: VectorStore,
    *,
    recreate: bool = False,
) -> dict[str, int]:
    """판정이 있는 모든 Ticket을 색인하고 처리·성공·건너뜀·실패 건수를 돌려준다."""
    if recreate and store.exists():
        store.drop_collection()
    store.ensure_collection()
    counts: dict[str, int] = {"processed": 0, "succeeded": 0, "skipped": 0, "failed": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM tickets WHERE verdict IS NOT NULL ORDER BY id"
            ).fetchall()
        ]
        for ticket_id in ids:
            counts["processed"] += 1
            try:
                done = index_ticket(conn, ticket_id, embedder, store)
            except Exception as exc:
                logger.warning("유사 사례 재색인 실패(%s)", type(exc).__name__)
                counts["failed"] += 1
                continue
            counts["succeeded" if done else "skipped"] += 1
    return counts


def make_indexer(embedder: Embedder, store: VectorStore) -> Any:
    """L1 워커에 넘길 색인 함수 (conn, ticket_id) -> None. 실패는 경고만 남기고 삼킨다(D-053)."""

    def indexer(conn: psycopg.Connection, ticket_id: str) -> None:
        try:
            index_ticket(conn, ticket_id, embedder, store)
        except Exception as exc:  # L1 판정은 이미 저장됐다. 누락은 재색인 명령으로 채운다
            logger.warning("유사 사례 색인 실패(%s)", type(exc).__name__)

    return indexer
