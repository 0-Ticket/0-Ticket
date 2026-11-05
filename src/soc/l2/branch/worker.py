"""실행기에서 escalated Ticket을 Incident에 분류하는 L2 워커."""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask, run_agent
from soc.l2.branch import build_branch
from soc.l2.branch.decide import (
    Candidate,
    Decision,
    final_candidates,
    make_task,
    parse_hits,
    provisional_candidates,
    recent_candidates,
    resolve_decision,
)
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.read import read_hit_tickets, read_incidents_by_ids, read_recent_incidents
from soc.l2.branch.store import save_branch
from soc.l2.config import BranchSettings, read_settings
from soc.store import (
    BgeM3Embedder,
    CollectionMismatch,
    CollectionMissing,
    Embedder,
    StoreError,
    VectorStore,
)
from soc.store.config import read_settings as read_store_settings

logger = logging.getLogger("soc.l2.branch")
Run = Callable[[AgentTask], AgentResult]


@dataclass(frozen=True)
class CandidateOutcome:
    items: tuple[Candidate, ...]
    source: str
    fallback: str | None
    invalid_hit_count: int
    vector: list[float] | None = None


class L2BranchWorker:
    stage = "l2"
    name = "l2_branch"

    def __init__(
        self,
        database_url: str,
        settings: BranchSettings,
        embedder: Embedder,
        vector_store: VectorStore,
        *,
        run: Run = run_agent,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._embedder = embedder
        self._store = vector_store
        self._run = run
        self._clock = clock

    def poll(self, limit: int) -> list[str]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT id FROM tickets WHERE status = 'escalated' ORDER BY id LIMIT %s",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, ticket_id: str) -> None:
        now = self._clock()
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            status = conn.execute(
                "SELECT status FROM tickets WHERE id = %s", (ticket_id,)
            ).fetchone()
            if status is None or status[0] != "escalated":
                return
            context = build_branch(conn, ticket_id)
            text = embedding_text(context)
            outcome = self._candidates(conn, text, now)
            if outcome.items:
                agent_result = self._run(make_task(context, outcome.items, outcome.source))
                if agent_result.failure == "cancelled":
                    return
                decision = resolve_decision(agent_result, outcome.items)
            else:
                decision = Decision(None, "no_candidates", None)
            details = {
                "candidate_source": outcome.source,
                "candidate_fallback": outcome.fallback,
                "invalid_hit_count": outcome.invalid_hit_count,
                "decision_source": decision.source,
                "decision_fallback": decision.fallback,
            }
            saved = save_branch(
                conn,
                context,
                decision,
                details,
                now_ms=int(now.timestamp() * 1000),
            )
        if saved.saved and text:
            self._index(ticket_id, saved.incident_id, text, outcome.vector)

    def _candidates(self, conn: psycopg.Connection, text: str, now: datetime) -> CandidateOutcome:
        if self._settings.candidate_source == "recent":
            return self._recent(conn, now, None, 0)
        if not text:
            return self._recent(conn, now, "empty_text", 0)
        vector = self._embedder.embed(text)
        try:
            found = self._store.search(vector, self._settings.top_k)
        except CollectionMismatch:
            raise
        except CollectionMissing:
            return self._recent(conn, now, "collection_missing", 0, vector)
        except StoreError:
            return self._recent(conn, now, "query_failed", 0, vector)

        parsed = parse_hits(found)
        lookup = read_incidents_by_ids(
            conn,
            list(dict.fromkeys(hit.incident_id for hit in parsed.hits)),
            now,
            self._settings.candidate_window_ms,
        )
        for incident_id in lookup.closed_ids:
            try:
                self._store.delete_by_payload("incident_id", incident_id)
            except StoreError as exc:
                logger.warning("닫힌 Incident point 삭제 실패(%s)", type(exc).__name__)
        provisional = provisional_candidates(
            parsed.hits,
            lookup.open,
            max_candidates=self._settings.max_candidates,
        )
        ticket_ids = list(dict.fromkeys(hit.ticket_id for item in provisional for hit in item.hits))
        selected = final_candidates(
            provisional,
            read_hit_tickets(conn, ticket_ids),
            invalid_count=parsed.invalid_count,
        )
        if selected.items:
            return CandidateOutcome(
                selected.items,
                "vector",
                None,
                selected.invalid_hit_count,
                vector,
            )
        return self._recent(
            conn,
            now,
            "no_valid_candidates",
            selected.invalid_hit_count,
            vector,
        )

    def _recent(
        self,
        conn: psycopg.Connection,
        now: datetime,
        fallback: str | None,
        invalid_hit_count: int,
        vector: list[float] | None = None,
    ) -> CandidateOutcome:
        incidents = read_recent_incidents(
            conn,
            now,
            self._settings.candidate_window_ms,
            limit=self._settings.max_candidates,
        )
        return CandidateOutcome(
            recent_candidates(incidents),
            "recent",
            fallback,
            invalid_hit_count,
            vector,
        )

    def _index(
        self,
        ticket_id: str,
        incident_id: str | None,
        text: str,
        vector: list[float] | None,
    ) -> None:
        if incident_id is None:
            raise AssertionError("저장된 Incident ID가 없다")
        try:
            self._store.upsert(
                ticket_id.removeprefix("tkt_"),
                self._embedder.embed(text) if vector is None else vector,
                {"incident_id": incident_id},
            )
        except Exception as exc:
            logger.warning("L2 Ticket 색인 실패(%s)", type(exc).__name__)


def build_worker(config: dict[str, Any]) -> L2BranchWorker:
    """전체 설정과 환경변수로 L2 분류 워커를 만든다."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    settings = read_settings(config["l2"])
    store_settings = read_store_settings(config["store"])
    embedder = BgeM3Embedder(store_settings.embedder)
    vector_store = VectorStore("ticket_branch", embedder, store_settings)
    try:
        vector_store.ensure_collection()
    except CollectionMismatch:
        raise
    except StoreError as exc:
        logger.warning("L2 vector 컬렉션 준비 실패(%s)", type(exc).__name__)
    return L2BranchWorker(database_url, settings, embedder, vector_store)
