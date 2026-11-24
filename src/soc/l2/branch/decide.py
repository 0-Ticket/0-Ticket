"""그래프 경로를 Incident 후보로 만들고 에이전트 분류 결과를 검사한다."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soc.agent import AgentResult, AgentTask, TaskPrompt
from soc.contracts.alert import alert_model_input
from soc.contracts.event import event_model_input
from soc.l2.branch.context import BranchContext

_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "l2_classify.md"


@dataclass(frozen=True)
class Candidate:
    incident: dict[str, Any]
    paths: tuple[dict[str, Any], ...]
    target_hosts: tuple[str, ...] = ()
    ticket_id: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class Decision:
    incident_id: str | None
    source: str
    fallback: str | None


def make_task(
    context: BranchContext,
    candidates: tuple[Candidate, ...],
    graph: dict[str, Any],
) -> AgentTask:
    """구조화 문맥과 코드가 계산한 후보 요약으로 L2 분류 작업을 만든다."""
    text = _PROMPT.read_text(encoding="utf-8")
    return AgentTask(
        stage="l2",
        task="l2_classify",
        prompt=TaskPrompt(text=text, version=hashlib.sha256(text.encode()).hexdigest()),
        data={
            "context": {
                "ticket": context.ticket,
                "alerts": [alert_model_input(alert) for alert in context.alerts],
                "events": [event_model_input(event) for event in context.events],
                "hunt": context.hunt,
                "evidence_ids": list(context.evidence_ids),
                "missing_evidence_count": context.missing_evidence_count,
            },
            "graph": graph,
            "candidates": [_candidate_data(candidate) for candidate in candidates],
        },
        output_contract="branch_decision",
        cited_ids=lambda _: (),
        subject_type="ticket",
        subject_id=context.ticket["id"],
        allowed_evidence_ids=(),
    )


def resolve_decision(result: AgentResult, candidates: tuple[Candidate, ...]) -> Decision:
    """이번 후보와 출력이 맞는지 검증한다. 오류는 새 Incident 판정이 아니다."""
    if not result.ok:
        return Decision(None, "error", result.failure)
    output = result.output
    if not isinstance(output, dict):
        return Decision(None, "error", "decision_mismatch")
    decision = output.get("decision")
    incident_id = output.get("incident_id")
    if decision == "new":
        if incident_id is not None:
            return Decision(None, "error", "decision_mismatch")
    elif decision == "existing":
        if not isinstance(incident_id, str):
            return Decision(None, "error", "decision_mismatch")
        if incident_id not in {candidate.incident["id"] for candidate in candidates}:
            return Decision(None, "error", "not_in_candidates")
    else:
        return Decision(None, "error", "decision_mismatch")
    similar = output.get("similar_ticket_ids")
    shown = {
        node["id"]
        for candidate in candidates
        for path in candidate.paths
        for node in path["nodes"]
        if node["kind"] == "ticket"
    }
    shown.update(c.ticket_id for c in candidates if c.ticket_id)
    if decision == "new" and similar != []:
        return Decision(None, "error", "similar_ticket_mismatch")
    if not isinstance(similar, list) or any(item not in shown for item in similar):
        return Decision(None, "error", "similar_ticket_mismatch")
    return Decision(incident_id, "agent", None)


def _candidate_data(candidate: Candidate) -> dict[str, Any]:
    incident = candidate.incident
    data = {
        "incident_id": incident["id"],
        "title": incident["title"],
        "summary": (incident.get("summary") or "")[:500],
        "ticket_count": len(incident["ticket_ids"]),
        "duration_ms": incident["updated_at"] - incident["created_at"],
        "paths": list(candidate.paths[:5]),
    }
    if candidate.ticket_id is not None:
        data["representative_ticket_id"] = candidate.ticket_id
    if candidate.score is not None:
        data["similarity_score"] = candidate.score
    if candidate.target_hosts:  # 값이 없으면 키를 생략해 빈 값이 "다름"으로 읽히지 않게 한다
        data["target_hosts"] = list(candidate.target_hosts)
    return data
