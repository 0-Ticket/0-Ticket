"""L2 분류 시나리오(#356)의 정규화 결과와 에이전트 입력 모양을 DB 없이 확인한다.

케이스 샘플은 tests/fixtures/l2/scenarios/cases.json이고 도우미는 tests/scenario_support.py다.
케이스 2의 Suricata 샘플은 손으로 만든 것이다. 아래 확인은 정규화기 규칙 기준이고, 실제 센서가
source·destination 방향을 이렇게 채우는지는 별도 확인이 필요하다.
"""

from typing import Any

import pytest
from scenario_support import CASES, all_alert_specs, normalize_spec

from soc.agent import AgentResult
from soc.contracts.alert import contract_data
from soc.l2.branch.context import BranchContext
from soc.l2.branch.decide import Candidate, make_task, resolve_decision

B_SPECS = [
    pytest.param(case["case"], spec, id=f"{case['case']}-{index}")
    for case in CASES
    for index, spec in enumerate(all_alert_specs(case))
    if "source" in spec
]
TICKET = "tkt_01a19f93-1150-7000-8000-000000000501"
PEER = "tkt_01a19f93-1150-7000-8000-000000000502"
INCIDENT = "inc_01a19f93-1150-7000-8000-000000000501"


@pytest.mark.parametrize(("case", "spec"), B_SPECS)
def test_normalizer_makes_the_roles_the_case_assumes(case: str, spec: dict[str, Any]) -> None:
    result = normalize_spec(spec)

    assert result.outcome == "ok", case
    assert result.source == spec["template"]
    assert [
        [entity["type"], entity["value"], entity["role"]] for entity in result.row["entities"]
    ] == spec["expect_entities"]


def test_every_case_has_a_valid_classification() -> None:
    allowed = {"일치", "불일치(결함)", "불일치(규칙의 결과)", "검증 불가"}

    assert {case["classification"] for case in CASES} <= allowed
    assert len({case["case"] for case in CASES}) == len(CASES)


def candidate_for(ticket: str = PEER) -> Candidate:
    path = {
        "incident_id": INCIDENT,
        "ticket_id": ticket,
        "nodes": [
            {"id": TICKET, "kind": "ticket"},
            {"id": "alt_01a19f93-1150-7000-8000-000000000501", "kind": "alert"},
            {"id": "ip:203.0.113.50", "kind": "entity", "type": "ip", "value": "203.0.113.50"},
            {"id": "alt_01a19f93-1150-7000-8000-000000000502", "kind": "alert"},
            {"id": ticket, "kind": "ticket"},
            {"id": INCIDENT, "kind": "incident"},
        ],
        "edges": [],
    }
    incident = {
        "id": INCIDENT,
        "title": "후보",
        "ticket_ids": [ticket],
        "created_at": 1793764000000,
        "updated_at": 1793764600000,
    }
    return Candidate(incident, (path,))


def result_of(output: dict[str, Any] | None, failure: str | None = None) -> AgentResult:
    return AgentResult(
        ok=failure is None,
        output=output,
        failure=failure,  # type: ignore[arg-type]
        detail=None,
        run_id="run_01a19f93-1150-7000-8000-000000000501",
    )


def test_agent_input_keeps_the_flat_alert_shape_with_roles() -> None:
    case = next(item for item in CASES if item["case"] == "1b-cross-source-same-src-ip")
    spec = case["current"][0]
    row = normalize_spec(spec).row
    alert = contract_data("alert", row)
    context = BranchContext(
        ticket={"id": TICKET, "verdict": None},
        alerts=(alert,),
        events=(),
        hunt=None,
        evidence_ids=(),
        missing_evidence_count=0,
    )
    graph = {"coverage": "complete", "reason": "paths_found", "paths": []}

    task = make_task(context, (candidate_for(),), graph)

    model_alert = task.data["context"]["alerts"][0]
    assert set(model_alert) == {
        "id",
        "raw_id",
        "time",
        "severity",
        "title",
        "rule_id",
        "entities",
        "assets",
        "triage",
        "ocsf",
        "details",
    }
    assert "details" not in model_alert["ocsf"]
    assert model_alert["ocsf"]["class_uid"] == 2004
    assert model_alert["entities"] == [
        {"type": "ip", "value": "203.0.113.50", "role": "src"},
        {"type": "ip", "value": "192.0.2.10", "role": "dst"},
    ]
    assert model_alert["id"] == alert["details"]["id"]


def test_candidate_summary_has_paths_but_no_entity_roles() -> None:
    task = make_task(
        BranchContext({"id": TICKET, "verdict": None}, (), (), None, (), 0),
        (candidate_for(),),
        {"coverage": "complete", "reason": "paths_found", "paths": []},
    )

    summary = task.data["candidates"][0]
    assert set(summary) == {"incident_id", "title", "ticket_count", "duration_ms", "paths"}
    entity_nodes = [
        node for path in summary["paths"] for node in path["nodes"] if node["kind"] == "entity"
    ]
    assert entity_nodes
    assert all("role" not in node for node in entity_nodes)


@pytest.mark.parametrize(
    ("output", "failure", "fallback"),
    [
        (None, "timeout", "timeout"),
        ({"decision": "existing", "incident_id": "inc_other"}, None, "not_in_candidates"),
        ({"decision": "new", "incident_id": INCIDENT}, None, "decision_mismatch"),
        (
            {"decision": "existing", "incident_id": INCIDENT, "similar_ticket_ids": ["tkt_none"]},
            None,
            "similar_ticket_mismatch",
        ),
    ],
)
def test_bad_agent_answers_fall_back_to_a_new_incident(
    output: dict[str, Any] | None, failure: str | None, fallback: str
) -> None:
    decision = resolve_decision(result_of(output, failure), (candidate_for(),))

    assert decision.incident_id is None
    assert decision.source == "rule_default"
    assert decision.fallback == fallback
