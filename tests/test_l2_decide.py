"""L2 그래프 후보와 에이전트 분류 결과를 확인한다."""

from typing import Any

import pytest
from fake_model import FakeModel
from test_agent_core import CONFIG, REGISTRY

from soc.agent import AgentResult
from soc.agent.agent_log import MemoryLogSink
from soc.agent.runner import run_task
from soc.agent.types import contains_forbidden
from soc.l2.branch.context import BranchContext
from soc.l2.branch.decide import Candidate, make_task, resolve_decision

INCIDENT = "inc_01a19f93-1150-7000-8000-000000000102"
PEER = "tkt_01a19f93-1150-7000-8000-000000000203"


def candidates() -> tuple[Candidate, ...]:
    path = {
        "incident_id": INCIDENT,
        "ticket_id": PEER,
        "nodes": [
            {"id": "tkt_01a19f93-1150-7000-8000-000000000301", "kind": "ticket"},
            {"id": "alt_01a19f93-1150-7000-8000-000000000301", "kind": "alert"},
            {"id": "host:ws-07", "kind": "entity", "type": "host", "value": "ws-07"},
            {"id": "alt_01a19f93-1150-7000-8000-000000000203", "kind": "alert"},
            {"id": PEER, "kind": "ticket"},
            {"id": INCIDENT, "kind": "incident"},
        ],
        "edges": [],
    }
    incident = {
        "id": INCIDENT,
        "title": "연결된 Incident",
        "ticket_ids": [PEER],
        "created_at": 1793764000000,
        "updated_at": 1793764600000,
    }
    return (Candidate(incident, (path,)),)


def candidate_context() -> BranchContext:
    return BranchContext(
        ticket={"id": "tkt_01a19f93-1150-7000-8000-000000000301", "verdict": None},
        alerts=(),
        events=(),
        hunt=None,
        evidence_ids=(),
        missing_evidence_count=0,
    )


def result(output: dict[str, Any] | None = None, failure: str | None = None) -> AgentResult:
    return AgentResult(
        ok=failure is None,
        output=output,
        failure=failure,  # type: ignore[arg-type]
        detail=None,
        run_id="run_01a19f93-1150-7000-8000-000000000001",
    )


def test_task_passes_graph_paths_and_candidate_summary() -> None:
    found = candidates()
    graph = {"coverage": "complete", "reason": "paths_found", "paths": list(found[0].paths)}

    task = make_task(candidate_context(), found, graph)

    assert task.output_contract == "branch_decision"
    assert task.data["graph"] == graph
    assert task.data["candidates"][0]["paths"] == list(found[0].paths)
    assert task.data["candidates"][0]["duration_ms"] == 600_000
    assert not contains_forbidden(task.prompt.text)


def test_result_accepts_ticket_shown_in_graph_path() -> None:
    found = candidates()

    decision = resolve_decision(
        result(
            {
                "decision": "existing",
                "incident_id": INCIDENT,
                "confidence": 0.9,
                "reason": "엔티티 경로가 이어진다",
                "similar_ticket_ids": [PEER],
            }
        ),
        found,
    )

    assert decision.incident_id == INCIDENT
    assert decision.source == "agent"
    assert decision.fallback is None


def test_vector_only_representative_is_valid_evidence() -> None:
    found = (Candidate(candidates()[0].incident, (), ticket_id=PEER, score=0.82),)
    task = make_task(candidate_context(), found, {"coverage": "complete", "paths": []})
    assert task.data["candidates"][0]["representative_ticket_id"] == PEER
    assert task.data["candidates"][0]["similarity_score"] == 0.82
    decision = resolve_decision(
        result({"decision": "existing", "incident_id": INCIDENT, "similar_ticket_ids": [PEER]}),
        found,
    )
    assert decision.incident_id == INCIDENT


def test_new_requires_empty_similar_ticket_ids() -> None:
    decision = resolve_decision(
        result({"decision": "new", "incident_id": None, "similar_ticket_ids": [PEER]}), candidates()
    )
    assert decision.source == "error"


def test_fake_model_output_passes_contract_and_candidate_checks() -> None:
    found = candidates()
    task = make_task(
        candidate_context(),
        found,
        {"coverage": "complete", "reason": "paths_found", "paths": list(found[0].paths)},
    )
    agent_result = run_task(
        task,
        model=FakeModel("l2_classify_existing"),
        model_name="fake-model",
        log_sink=MemoryLogSink(),
        config=CONFIG,
        registry=REGISTRY,
    )

    assert resolve_decision(agent_result, found).incident_id == INCIDENT


@pytest.mark.parametrize(
    ("output", "failure", "expected"),
    [
        (
            {
                "decision": "existing",
                "incident_id": "inc_01a19f93-1150-7000-8000-000000000199",
                "similar_ticket_ids": [],
            },
            None,
            "not_in_candidates",
        ),
        (
            {"decision": "new", "incident_id": "inc_bad", "similar_ticket_ids": []},
            None,
            "decision_mismatch",
        ),
        (
            {
                "decision": "existing",
                "incident_id": INCIDENT,
                "similar_ticket_ids": ["tkt_01a19f93-1150-7000-8000-000000000299"],
            },
            None,
            "similar_ticket_mismatch",
        ),
        (None, "provider_error", "provider_error"),
    ],
)
def test_bad_result_is_an_error_not_a_new_decision(
    output: dict[str, Any] | None, failure: str | None, expected: str
) -> None:
    decision = resolve_decision(result(output, failure), candidates())

    assert decision.incident_id is None
    assert decision.source == "error"
    assert decision.fallback == expected
