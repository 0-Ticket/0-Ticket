"""L2 분류 문맥과 임베딩 텍스트를 손으로 만든 샘플로 확인한다."""

import json
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import validate_contract
from soc.l2.branch.context import build_context
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.read import BranchRows

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
EMBEDDING_FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "embedding.json"


@pytest.fixture(scope="module")
def sample() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_contracts_are_valid(sample: dict[str, Any]) -> None:
    contracts = {
        "raw_records": "raw_record",
        "alerts": "alert",
        "events": "event",
        "hunts": "hunt",
        "tickets": "ticket",
        "agent_logs": "agent_log",
        "incidents": "incident",
    }

    for group, contract in contracts.items():
        for data in sample[group]:
            assert validate_contract(contract, data).model_dump(mode="json") == data


def rows_for(sample: dict[str, Any], ticket_index: int) -> BranchRows:
    ticket = sample["tickets"][ticket_index]
    if ticket["origin"] == "l3":
        return BranchRows(
            ticket=ticket,
            alerts=(),
            events=(sample["events"][1],),
            hunt=sample["hunts"][0],
            evidence_ids=(
                sample["events"][1]["id"],
                sample["agent_logs"][1]["id"],
            ),
            missing_evidence_count=1,
        )
    return BranchRows(
        ticket=ticket,
        alerts=(sample["alerts"][0],),
        events=(sample["events"][0],),
        hunt=None,
        evidence_ids=(
            sample["alerts"][0]["id"],
            sample["events"][0]["id"],
            sample["agent_logs"][0]["id"],
        ),
        missing_evidence_count=1,
    )


def test_context_keeps_confirmed_data(sample: dict[str, Any]) -> None:
    context = build_context(rows_for(sample, 0))

    assert context.ticket["id"] == sample["tickets"][0]["id"]
    assert [alert["id"] for alert in context.alerts] == [sample["alerts"][0]["id"]]
    assert [event["id"] for event in context.events] == [sample["events"][0]["id"]]
    assert context.hunt is None
    assert context.missing_evidence_count == 1


def test_l3_context_uses_hunt_evidence(sample: dict[str, Any]) -> None:
    context = build_context(rows_for(sample, 1))

    assert context.alerts == ()
    assert context.hunt == sample["hunts"][0]
    assert [event["id"] for event in context.events] == [sample["events"][1]["id"]]
    assert context.missing_evidence_count == 1


def test_embedding_text_keeps_order_drops_empty_values_and_has_no_labels() -> None:
    cases = json.loads(EMBEDDING_FIXTURE.read_text(encoding="utf-8"))["cases"]

    for case in cases:
        context = type("Context", (), case)()
        assert embedding_text(context) == case["expected"]
