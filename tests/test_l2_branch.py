"""L2 분류 문맥·신호·후보 순위를 손으로 만든 샘플로 확인한다."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import validate_contract
from soc.entities import normalize_entity_value
from soc.l2.branch.candidates import rank_candidates
from soc.l2.branch.context import build_context
from soc.l2.branch.read import BranchRows
from soc.l2.branch.signals import classify_entities
from soc.l2.config import BranchSettings

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
SETTINGS = BranchSettings(
    candidate_window_ms=86_400_000,
    max_candidates=5,
    strong_signal_types=frozenset({"file_hash", "process", "url", "domain", "user"}),
    weak_signal_types=frozenset({"ip", "host"}),
    shared_entity_values=("shared-proxy",),
)


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
            incidents=tuple(sample["incidents"][:3]),
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
        incidents=tuple(sample["incidents"][:3]),
    )


def test_context_keeps_confirmed_data_and_normalized_signals(sample: dict[str, Any]) -> None:
    context = build_context(rows_for(sample, 0), SETTINGS)

    assert context.ticket["id"] == sample["tickets"][0]["id"]
    assert [alert["id"] for alert in context.alerts] == [sample["alerts"][0]["id"]]
    assert [event["id"] for event in context.events] == [sample["events"][0]["id"]]
    assert context.hunt is None
    assert context.missing_evidence_count == 1
    assert {signal.key: signal.level for signal in context.signals} == {
        ("file_hash", "abcdef1234"): "strong",
        ("process", "/Opt/Tool"): "strong",
        ("url", "https://Example.com/Path"): "strong",
        ("domain", "example.com"): "strong",
        ("user", "admin"): "strong",
        ("ip", "2001:db8::1"): "weak",
        ("host", "shared-proxy"): "shared",
    }
    assert next(signal for signal in context.signals if signal.type == "user").role == "actor"


def test_l3_context_uses_hunt_evidence_and_entities_without_duplicates(
    sample: dict[str, Any],
) -> None:
    context = build_context(rows_for(sample, 1), SETTINGS)

    assert context.alerts == ()
    assert context.hunt == sample["hunts"][0]
    assert [event["id"] for event in context.events] == [sample["events"][1]["id"]]
    assert context.missing_evidence_count == 1
    assert [signal.key for signal in context.signals].count(("domain", "beacon.example")) == 1
    assert ("host", "ws-07") in {signal.key for signal in context.signals}


def test_normalization_is_type_specific_and_shared_wins() -> None:
    entities = [
        {"type": "ip", "value": " 2001:0DB8:0:0::1 ", "role": "src"},
        {"type": "user", "value": " Root ", "role": "actor"},
        {"type": "url", "value": " HTTPS://Example/Path ", "role": "target"},
        {"type": "process", "value": " /Opt/Tool ", "role": "actor"},
        {"type": "host", "value": " SHARED-PROXY ", "role": "dst"},
    ]

    signals = classify_entities(entities, SETTINGS)

    assert normalize_entity_value("ip", entities[0]["value"]) == "2001:db8::1"
    assert [(signal.value, signal.level) for signal in signals] == [
        ("2001:db8::1", "weak"),
        ("root", "strong"),
        ("HTTPS://Example/Path", "strong"),
        ("/Opt/Tool", "strong"),
        ("shared-proxy", "shared"),
    ]


def test_candidates_rank_by_strong_weak_then_updated_at(sample: dict[str, Any]) -> None:
    context = build_context(rows_for(sample, 0), SETTINGS)

    candidates = rank_candidates(context.signals, rows_for(sample, 0).incidents, SETTINGS)

    assert [
        (item.incident["id"], item.strong_matches, item.weak_matches) for item in candidates
    ] == [
        (sample["incidents"][0]["id"], 2, 1),
        (sample["incidents"][1]["id"], 1, 1),
        (sample["incidents"][2]["id"], 0, 1),
    ]


def test_candidates_stop_at_configured_maximum(sample: dict[str, Any]) -> None:
    settings = replace(SETTINGS, max_candidates=2)
    context = build_context(rows_for(sample, 0), settings)

    assert len(rank_candidates(context.signals, rows_for(sample, 0).incidents, settings)) == 2
