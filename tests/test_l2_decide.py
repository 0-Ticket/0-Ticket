"""L2 vector 후보와 에이전트 분류 결과를 순수 계산으로 확인한다."""

import json
from pathlib import Path
from typing import Any

import pytest

from soc.agent import AgentResult
from soc.agent.types import contains_forbidden
from soc.l2.branch.context import BranchContext
from soc.l2.branch.decide import (
    final_candidates,
    make_task,
    parse_hits,
    provisional_candidates,
    resolve_decision,
)
from soc.store import SearchHit

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "candidates.json"


@pytest.fixture(scope="module")
def sample() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def search_hits(sample: dict[str, Any]) -> tuple[SearchHit, ...]:
    return tuple(SearchHit(**hit) for hit in sample["hits"])


def test_invalid_hit_shapes_are_dropped(sample: dict[str, Any]) -> None:
    parsed = parse_hits(search_hits(sample))

    assert parsed.invalid_count == 2
    assert len(parsed.hits) == 4


def test_relationship_check_reselects_and_resorts_without_refill(sample: dict[str, Any]) -> None:
    parsed = parse_hits(search_hits(sample))
    incidents = {row["id"]: row for row in sample["incidents"]}
    tickets = {row["id"]: row for row in sample["tickets"]}

    provisional = provisional_candidates(parsed.hits, incidents, max_candidates=2)
    selected = final_candidates(provisional, tickets, invalid_count=parsed.invalid_count)

    actual = [(item.incident["id"], item.score, item.similar_ticket_id) for item in selected.items]
    assert actual == [
        (
            "inc_01a19f93-1150-7000-8000-000000000102",
            0.90,
            "tkt_01a19f93-1150-7000-8000-000000000203",
        ),
        (
            "inc_01a19f93-1150-7000-8000-000000000101",
            0.80,
            "tkt_01a19f93-1150-7000-8000-000000000202",
        ),
    ]
    assert selected.invalid_hit_count == 3
    assert all(item.incident["id"] != sample["incidents"][2]["id"] for item in selected.items)


def test_all_invalid_relations_leave_no_candidates(sample: dict[str, Any]) -> None:
    parsed = parse_hits(search_hits(sample))
    incidents = {row["id"]: row for row in sample["incidents"]}
    tickets = {row["id"]: {**row, "status": "escalated"} for row in sample["tickets"]}

    selected = final_candidates(
        provisional_candidates(parsed.hits, incidents, max_candidates=2),
        tickets,
        invalid_count=parsed.invalid_count,
    )

    assert selected.items == ()
    assert selected.invalid_hit_count == 5


def candidate_context() -> BranchContext:
    ticket_id = "tkt_01a19f93-1150-7000-8000-000000000301"
    return BranchContext(
        ticket={"id": ticket_id, "verdict": None},
        alerts=(),
        events=(),
        hunt=None,
        evidence_ids=(),
        missing_evidence_count=0,
    )


def test_task_contains_duration_and_contract_without_forbidden_prompt(
    sample: dict[str, Any],
) -> None:
    parsed = parse_hits(search_hits(sample))
    selected = final_candidates(
        provisional_candidates(
            parsed.hits, {row["id"]: row for row in sample["incidents"]}, max_candidates=2
        ),
        {row["id"]: row for row in sample["tickets"]},
    )

    task = make_task(candidate_context(), selected.items, "vector")

    assert task.output_contract == "branch_decision"
    assert task.allowed_evidence_ids == ()
    assert task.data["candidate_source"] == "vector"
    assert task.data["candidates"][0]["duration_ms"] == 600_000
    assert "created_at" not in task.data["candidates"][0]
    assert "updated_at" not in task.data["candidates"][0]
    assert not contains_forbidden(task.prompt.text)


def result(output: dict[str, Any] | None = None, failure: str | None = None) -> AgentResult:
    return AgentResult(
        ok=failure is None,
        output=output,
        failure=failure,  # type: ignore[arg-type]
        detail=None,
        run_id="run_01a19f93-1150-7000-8000-000000000001",
    )


def test_result_accepts_shown_candidate_and_similar_ticket(sample: dict[str, Any]) -> None:
    parsed = parse_hits(search_hits(sample))
    candidates = final_candidates(
        provisional_candidates(
            parsed.hits, {row["id"]: row for row in sample["incidents"]}, max_candidates=2
        ),
        {row["id"]: row for row in sample["tickets"]},
    ).items

    decision = resolve_decision(
        result(
            {
                "decision": "existing",
                "incident_id": candidates[0].incident["id"],
                "confidence": 0.9,
                "reason": "같은 활동이다",
                "similar_ticket_ids": [candidates[0].similar_ticket_id],
            }
        ),
        candidates,
    )

    assert decision.incident_id == candidates[0].incident["id"]
    assert decision.source == "agent"
    assert decision.fallback is None


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
                "incident_id": "inc_01a19f93-1150-7000-8000-000000000102",
                "similar_ticket_ids": ["tkt_01a19f93-1150-7000-8000-000000000299"],
            },
            None,
            "similar_ticket_mismatch",
        ),
        (None, "provider_error", "provider_error"),
    ],
)
def test_bad_result_falls_back_to_new(
    sample: dict[str, Any], output: dict[str, Any] | None, failure: str | None, expected: str
) -> None:
    parsed = parse_hits(search_hits(sample))
    candidates = final_candidates(
        provisional_candidates(
            parsed.hits, {row["id"]: row for row in sample["incidents"]}, max_candidates=2
        ),
        {row["id"]: row for row in sample["tickets"]},
    ).items

    decision = resolve_decision(result(output, failure), candidates)

    assert decision.incident_id is None
    assert decision.source == "rule_default"
    assert decision.fallback == expected
