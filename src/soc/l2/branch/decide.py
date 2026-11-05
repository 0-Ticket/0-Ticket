"""벡터 hit를 Incident 후보로 만들고 에이전트 분류 결과를 검사한다."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soc.agent import AgentResult, AgentTask, TaskPrompt
from soc.l2.branch.context import BranchContext
from soc.store import SearchHit

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_POINT_ID = re.compile(rf"{_UUID7}\Z")
_INCIDENT_ID = re.compile(rf"inc_{_UUID7}\Z")
_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "l2_classify.md"


@dataclass(frozen=True)
class VectorHit:
    incident_id: str
    ticket_id: str
    score: float


@dataclass(frozen=True)
class ParsedHits:
    hits: tuple[VectorHit, ...]
    invalid_count: int


@dataclass(frozen=True)
class IncidentHits:
    incident: dict[str, Any]
    hits: tuple[VectorHit, ...]


@dataclass(frozen=True)
class Candidate:
    incident: dict[str, Any]
    score: float | None = None
    similar_ticket_id: str | None = None
    similar_ticket_title: str | None = None


@dataclass(frozen=True)
class CandidateSelection:
    items: tuple[Candidate, ...]
    invalid_hit_count: int


@dataclass(frozen=True)
class Decision:
    incident_id: str | None
    source: str
    fallback: str | None


def parse_hits(hits: tuple[SearchHit, ...]) -> ParsedHits:
    """point UUID와 payload Incident ID가 맞는 hit만 Ticket ID로 복원한다."""
    valid = []
    invalid = 0
    for hit in hits:
        incident_id = hit.payload.get("incident_id")
        if (
            not _POINT_ID.fullmatch(hit.point_id)
            or not isinstance(incident_id, str)
            or not _INCIDENT_ID.fullmatch(incident_id)
        ):
            invalid += 1
            continue
        valid.append(VectorHit(incident_id, f"tkt_{hit.point_id}", hit.score))
    return ParsedHits(tuple(valid), invalid)


def provisional_candidates(
    hits: tuple[VectorHit, ...],
    incidents: dict[str, dict[str, Any]],
    *,
    max_candidates: int,
) -> tuple[IncidentHits, ...]:
    """유효 Incident마다 hit를 점수순으로 모아 임시 상위 후보를 고른다."""
    grouped: dict[str, list[VectorHit]] = {}
    for hit in hits:
        if hit.incident_id in incidents:
            grouped.setdefault(hit.incident_id, []).append(hit)
    candidates = [
        IncidentHits(incidents[incident_id], tuple(sorted(found, key=_hit_score, reverse=True)))
        for incident_id, found in grouped.items()
    ]
    candidates.sort(key=lambda item: item.hits[0].score, reverse=True)
    return tuple(candidates[:max_candidates])


def final_candidates(
    provisional: tuple[IncidentHits, ...],
    tickets: dict[str, dict[str, Any]],
    *,
    invalid_count: int = 0,
) -> CandidateSelection:
    """PostgreSQL 소속 관계를 통과한 최고 hit로 후보를 다시 세운다. 탈락 자리는 안 채운다."""
    out = []
    invalid = invalid_count
    for item in provisional:
        ticket_ids = set(item.incident["ticket_ids"])
        valid = []
        for hit in item.hits:
            ticket = tickets.get(hit.ticket_id)
            if (
                ticket is None
                or ticket.get("status") != "linked"
                or hit.ticket_id not in ticket_ids
            ):
                invalid += 1
                continue
            valid.append(hit)
        if not valid:
            continue
        best = max(valid, key=_hit_score)
        out.append(
            Candidate(
                incident=item.incident,
                score=best.score,
                similar_ticket_id=best.ticket_id,
                similar_ticket_title=tickets[best.ticket_id].get("title"),
            )
        )
    out.sort(key=lambda item: item.score if item.score is not None else -1.0, reverse=True)
    return CandidateSelection(tuple(out), invalid)


def recent_candidates(incidents: tuple[dict[str, Any], ...]) -> tuple[Candidate, ...]:
    """recent 조회가 이미 정렬·절단한 Incident를 에이전트 후보로 바꾼다."""
    return tuple(Candidate(incident) for incident in incidents)


def make_task(
    context: BranchContext, candidates: tuple[Candidate, ...], candidate_source: str
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
                "alerts": list(context.alerts),
                "events": list(context.events),
                "hunt": context.hunt,
                "evidence_ids": list(context.evidence_ids),
                "missing_evidence_count": context.missing_evidence_count,
            },
            "candidate_source": candidate_source,
            "candidates": [_candidate_data(candidate) for candidate in candidates],
        },
        output_contract="branch_decision",
        cited_ids=lambda _: (),
        subject_type="ticket",
        subject_id=context.ticket["id"],
        allowed_evidence_ids=(),
    )


def resolve_decision(result: AgentResult, candidates: tuple[Candidate, ...]) -> Decision:
    """성공한 출력이 이번 후보와 맞는지 보고, 아니면 새 Incident 규칙으로 떨어뜨린다."""
    if not result.ok:
        return Decision(None, "rule_default", result.failure)
    output = result.output
    if not isinstance(output, dict):
        return Decision(None, "rule_default", "decision_mismatch")
    decision = output.get("decision")
    incident_id = output.get("incident_id")
    if decision == "new":
        if incident_id is not None:
            return Decision(None, "rule_default", "decision_mismatch")
    elif decision == "existing":
        if not isinstance(incident_id, str):
            return Decision(None, "rule_default", "decision_mismatch")
        if incident_id not in {candidate.incident["id"] for candidate in candidates}:
            return Decision(None, "rule_default", "not_in_candidates")
    else:
        return Decision(None, "rule_default", "decision_mismatch")
    similar = output.get("similar_ticket_ids")
    shown = {candidate.similar_ticket_id for candidate in candidates}
    if not isinstance(similar, list) or any(item not in shown for item in similar):
        return Decision(None, "rule_default", "similar_ticket_mismatch")
    return Decision(incident_id, "agent", None)


def _candidate_data(candidate: Candidate) -> dict[str, Any]:
    incident = candidate.incident
    return {
        "incident_id": incident["id"],
        "title": incident["title"],
        "ticket_count": len(incident["ticket_ids"]),
        "duration_ms": incident["updated_at"] - incident["created_at"],
        "similarity": candidate.score,
        "similar_ticket": (
            None
            if candidate.similar_ticket_id is None
            else {"id": candidate.similar_ticket_id, "title": candidate.similar_ticket_title}
        ),
    }


def _hit_score(hit: VectorHit) -> float:
    return hit.score
