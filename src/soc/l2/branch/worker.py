"""모든 유사 Ticket 후보를 이어서 검토하고 Incident 분류를 저장하는 L2 워커."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.agent import AgentResult, AgentTask, run_agent
from soc.l2.branch import build_branch
from soc.l2.branch.candidates import find_candidates, index_ready
from soc.l2.branch.decide import Candidate, Decision, make_task, resolve_decision
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.graph import read_graph
from soc.l2.branch.runtime import BranchService, get_service
from soc.l2.branch.store import save_branch
from soc.l2.config import BranchSettings, read_settings
from soc.store.config import StoreSettings
from soc.store.config import read_settings as read_store_settings

Run = Callable[[AgentTask], AgentResult]


class BranchFailure(Exception):
    pass


def _snapshot(vectors: Any) -> list[dict[str, Any]]:
    return [
        {
            "incident_id": item.incident["id"],
            "ticket_id": item.ticket_id,
            "score": round(item.score, 6),
            "updated_at": item.incident["updated_at"],
        }
        for item in vectors
    ]


@dataclass(frozen=True)
class L2BranchWorker:
    database_url: str
    settings: BranchSettings
    run: Run = run_agent
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    store_settings: StoreSettings | None = None
    service: BranchService | None = None

    stage = "l2"
    name = "l2_branch"

    def poll(self, limit: int) -> list[str]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        now_ms = int(self.clock().timestamp() * 1000)
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            rows = conn.execute(
                """SELECT id FROM tickets WHERE status = 'escalated'
                AND COALESCE((details #>> '{l2_branch,next_retry_at}')::bigint, 0) <= %s
                ORDER BY id LIMIT %s""",
                (now_ms, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, ticket_id: str) -> None:
        now = self.clock()
        now_ms = int(now.timestamp() * 1000)
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            row = conn.execute(
                "SELECT status, details #>> '{l2_branch,next_retry_at}' FROM tickets WHERE id = %s",
                (ticket_id,),
            ).fetchone()
            if row is None or row[0] != "escalated" or row[1] and int(row[1]) > now_ms:
                return
            try:
                service = self.service or get_service(self.store_settings)  # type: ignore[arg-type]
                if not index_ready(conn, service):
                    _record(conn, ticket_id, {"coverage": "incomplete", "reason": "index_pending"})
                    return
                context = build_branch(conn, ticket_id)
                vectors = find_candidates(
                    conn,
                    service,
                    embedding_text(context),
                    ticket_id,
                    min_score=self.settings.min_score,
                    max_incident_tickets=self.settings.max_incident_tickets,
                )
                sources = tuple(
                    {
                        "kind": "alert",
                        "id": alert["details"]["id"],
                        "entities": alert["details"]["entities"],
                    }
                    for alert in context.alerts
                )
                if not sources and context.hunt is not None:
                    sources = (
                        {
                            "kind": "hunt",
                            "id": context.hunt["id"],
                            "entities": context.hunt["entities"],
                        },
                    )
                graph = read_graph(
                    conn,
                    ticket_id,
                    sources,
                    now,
                    candidate_window_ms=self.settings.candidate_window_ms,
                    max_candidates=self.settings.max_candidates,
                    max_incident_tickets=self.settings.max_incident_tickets,
                    incident_ids=tuple(item.incident["id"] for item in vectors),
                )
                paths = {candidate.incident_id: candidate.paths for candidate in graph.candidates}
                candidates = tuple(
                    Candidate(
                        item.incident,
                        paths.get(item.incident["id"], ()),
                        item.target_hosts,
                        item.ticket_id,
                        item.score,
                    )
                    for item in vectors
                )
                snapshot = _snapshot(vectors)
                previous = context.ticket["details"].get("l2_branch", {})
                progress = (
                    previous.get("progress", {}) if previous.get("snapshot") == snapshot else {}
                )
                state = {
                    "coverage": "complete",
                    "reason": graph.reason if candidates else "no_similar_candidate",
                    "paths": list(graph.paths[:50]),
                    "candidates": snapshot,
                    "snapshot": snapshot,
                    "progress": progress,
                    "failures": previous.get("failures", 0),
                }
                if not candidates:
                    self._finish(
                        conn,
                        context,
                        Decision(None, "vector_default", "no_similar_candidate"),
                        state,
                        now_ms,
                        service,
                        snapshot,
                    )
                    return
                self._classify(conn, context, candidates, state, now_ms, service, snapshot)
            except BranchFailure as exc:
                _failure(conn, ticket_id, str(exc), now_ms, self.settings)
            except Exception as exc:
                _failure(conn, ticket_id, type(exc).__name__, now_ms, self.settings)

    def _classify(
        self,
        conn: psycopg.Connection,
        context: Any,
        candidates: tuple[Candidate, ...],
        state: dict[str, Any],
        now_ms: int,
        service: BranchService,
        snapshot: list[dict[str, Any]],
    ) -> None:
        by_id = {candidate.incident["id"]: candidate for candidate in candidates}
        progress = state["progress"] or {
            "phase": "initial",
            "pool": list(by_id),
            "cursor": 0,
            "winners": [],
        }
        calls = 0
        while calls < self.settings.max_calls_per_cycle:
            pool = progress["pool"]
            batch = tuple(
                by_id[key]
                for key in pool[
                    progress["cursor"] : progress["cursor"] + self.settings.max_candidates
                ]
            )
            if not batch:
                raise BranchFailure("empty_batch")
            result = self.run(
                make_task(
                    context,
                    batch,
                    {
                        "coverage": "complete",
                        "reason": "paths_found"
                        if any(item.paths for item in batch)
                        else "vector_only",
                        "paths": [path for item in batch for path in item.paths[:5]],
                        "phase": progress["phase"],
                    },
                )
            )
            if result.failure == "cancelled":
                return
            decision = resolve_decision(result, batch)
            if decision.source == "error":
                raise BranchFailure(decision.fallback or "model_error")
            calls += 1
            if decision.incident_id is not None:
                progress["winners"].append(decision.incident_id)
            progress["cursor"] += len(batch)
            state["progress"] = progress
            if progress["cursor"] < len(pool):
                _record(conn, context.ticket["id"], state)
                continue
            if progress["phase"] == "initial" and len(pool) <= self.settings.max_candidates:
                self._finish(conn, context, decision, state, now_ms, service, snapshot)
                return
            winners = list(dict.fromkeys(progress["winners"]))
            if not winners:
                self._finish(
                    conn, context, Decision(None, "agent", None), state, now_ms, service, snapshot
                )
                return
            if progress["phase"] == "final" and len(pool) <= self.settings.max_candidates:
                self._finish(conn, context, decision, state, now_ms, service, snapshot)
                return
            progress = {"phase": "final", "pool": winners, "cursor": 0, "winners": []}
            state["progress"] = progress
            _record(conn, context.ticket["id"], state)
        _record(conn, context.ticket["id"], state)

    def _finish(
        self,
        conn: psycopg.Connection,
        context: Any,
        decision: Decision,
        state: dict[str, Any],
        now_ms: int,
        service: BranchService,
        snapshot: list[dict[str, Any]],
    ) -> None:
        if not index_ready(conn, service):
            state["coverage"] = "incomplete"
            state["reason"] = "index_pending"
            _record(conn, context.ticket["id"], state)
            return
        fresh = find_candidates(
            conn,
            service,
            embedding_text(context),
            context.ticket["id"],
            min_score=self.settings.min_score,
            max_incident_tickets=self.settings.max_incident_tickets,
        )
        if _snapshot(fresh) != snapshot:
            state["reason"] = "candidates_changed"
            state["progress"] = {}
            _record(conn, context.ticket["id"], state)
            return
        details = {
            **state,
            "decision_source": decision.source,
            "decision_fallback": decision.fallback,
        }
        details.pop("progress", None)
        saved = save_branch(
            conn,
            context,
            decision,
            details,
            now_ms=now_ms,
            max_incident_tickets=self.settings.max_incident_tickets,
        )
        if not saved.saved and saved.reason:
            raise BranchFailure(saved.reason)


def _record(conn: psycopg.Connection, ticket_id: str, state: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE tickets SET details = jsonb_set(details, '{l2_branch}', %s),
        updated_at = now() WHERE id = %s AND status = 'escalated'""",
        (Jsonb(state), ticket_id),
    )


def _failure(
    conn: psycopg.Connection,
    ticket_id: str,
    reason: str,
    now_ms: int,
    settings: BranchSettings,
) -> None:
    with conn.transaction():
        row = conn.execute(
            "SELECT details FROM tickets WHERE id = %s AND status = 'escalated' FOR UPDATE",
            (ticket_id,),
        ).fetchone()
        if row is None:
            return
        previous = row[0].get("l2_branch", {})
        failures = previous.get("failures", 0) + 1
        state = {
            **previous,
            "coverage": "incomplete",
            "reason": reason,
            "failures": failures,
            "next_retry_at": now_ms + settings.failure_retry_delay_ms,
        }
        if failures >= settings.max_failures:
            state["held_by"] = "l2_branch"
        conn.execute(
            """UPDATE tickets SET status = %s,
            details = jsonb_set(details, '{l2_branch}', %s), updated_at = now()
            WHERE id = %s""",
            ("held" if failures >= settings.max_failures else "escalated", Jsonb(state), ticket_id),
        )


def build_worker(config: dict[str, Any]) -> L2BranchWorker:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    return L2BranchWorker(
        database_url,
        read_settings(config["l2"]),
        store_settings=read_store_settings(config["store"]),
    )
