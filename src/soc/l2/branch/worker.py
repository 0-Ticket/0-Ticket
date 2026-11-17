"""실행기에서 escalated Ticket을 Incident에 그래프 분류하는 L2 워커."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask, run_agent
from soc.l2.branch import build_branch
from soc.l2.branch.decide import Candidate, Decision, make_task, resolve_decision
from soc.l2.branch.graph import read_graph
from soc.l2.branch.store import save_branch
from soc.l2.config import BranchSettings, read_settings

Run = Callable[[AgentTask], AgentResult]


@dataclass(frozen=True)
class L2BranchWorker:
    database_url: str
    settings: BranchSettings
    run: Run = run_agent
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    stage = "l2"
    name = "l2_branch"

    def poll(self, limit: int) -> list[str]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT id FROM tickets WHERE status = 'escalated' ORDER BY id LIMIT %s",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, ticket_id: str) -> None:
        now = self.clock()
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            status = conn.execute(
                "SELECT status FROM tickets WHERE id = %s", (ticket_id,)
            ).fetchone()
            if status is None or status[0] != "escalated":
                return
            context = build_branch(conn, ticket_id)
            sources = tuple(
                {"kind": "alert", "id": alert["id"], "entities": alert["entities"]}
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
            )
            candidates = tuple(
                Candidate(candidate.incident, candidate.paths) for candidate in graph.candidates
            )
            if graph.coverage == "complete" and candidates:
                result = self.run(make_task(context, candidates, graph.as_dict()))
                if result.failure == "cancelled":
                    return
                decision = resolve_decision(result, candidates)
            else:
                decision = Decision(None, "graph_default", graph.reason)
            details = {
                **graph.as_dict(),
                "decision_source": decision.source,
                "decision_fallback": decision.fallback,
            }
            save_branch(
                conn,
                context,
                decision,
                details,
                now_ms=int(now.timestamp() * 1000),
                max_incident_tickets=self.settings.max_incident_tickets,
            )


def build_worker(config: dict[str, Any]) -> L2BranchWorker:
    """전체 설정과 환경변수로 L2 분류 워커를 만든다."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    return L2BranchWorker(database_url, read_settings(config["l2"]))
