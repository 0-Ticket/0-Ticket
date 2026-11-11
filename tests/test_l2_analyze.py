"""L2 Incident 분석의 근거 평탄화와 조회 구간을 확인한다."""

import json
from pathlib import Path

from soc.l2.analyze.context import _pick_evenly, _seed_entities, calculate_window
from soc.l2.analyze.store import build_records
from soc.l2.analyze.tasks import analysis_citations, findings_citations, make_report_task
from soc.l2.analyze.worker import should_retry_report

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "analyze.json"
RELATED = Path(__file__).parent / "fixtures" / "l2" / "related.json"
INCIDENT_ID = "inc_01a19f93-1150-7000-8000-000000000003"


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_nested_evidence_is_flattened_in_first_seen_order() -> None:
    data = sample()

    assert findings_citations(data["findings"]) == [
        "agl_01a19f93-1150-7000-8000-000000000009",
        "evt_01a19f93-1150-7000-8000-000000000005",
        "alt_01a19f93-1150-7000-8000-000000000004",
    ]
    assert analysis_citations(data["analysis"]) == [
        "agl_01a19f93-1150-7000-8000-000000000010",
        "evt_01a19f93-1150-7000-8000-000000000005",
    ]


def test_window_covers_old_evidence_without_tool_range_floor() -> None:
    window = calculate_window(
        earliest_ms=1_790_000_000_000,
        now_ms=1_800_000_000_000,
        lookback_ms=259_200_000,
    )

    assert window == {"from": 1_789_740_800_000, "to": 1_800_000_000_000}


def test_related_round_robin_spreads_time_and_kind_and_donates_empty_slots() -> None:
    fixture = json.loads(RELATED.read_text(encoding="utf-8"))
    items = [(item["entity"], item["bucket"], item["kind"], item["record"]) for item in fixture]
    selected = _pick_evenly(items, 8)
    assert {row["id"] for _, _, _, row in selected} == {item["record"]["id"] for item in fixture}

    sparse = [(0, 3, "alert", {"id": f"alt_{n}", "time": n}) for n in range(25)]
    sparse.append(items[1])
    selected = _pick_evenly(sparse, 20)
    assert len(selected) == 20
    assert any(kind == "event" for _, _, kind, _ in selected)


def test_global_related_cap_gives_all_entities_a_turn() -> None:
    fixture = json.loads(RELATED.read_text(encoding="utf-8"))
    items = [
        (
            entity,
            item["bucket"],
            item["kind"],
            {**item["record"], "id": f"{entity}-{item['record']['id']}"},
        )
        for entity in range(10)
        for item in fixture
    ]
    items.append((9, 3, "alert", {"id": "extra", "time": 42}))

    selected = _pick_evenly(items, 80)

    assert len(selected) == 80
    assert {entity for entity, _, _, _ in selected} == set(range(10))
    assert {kind for _, _, kind, _ in selected} == {"alert", "event"}
    assert {bucket for _, bucket, _, _ in selected} == set(range(4))


def test_seed_entities_use_link_order_not_ticket_creation_time() -> None:
    existing = [
        {"type": "host", "value": f"old-{number}", "role": "target"} for number in range(11)
    ]
    recent = {"type": "host", "value": "recent", "role": "target"}
    incident = {"ticket_ids": ["old", "recent"], "entities": [*existing, recent]}
    tickets = [
        {"id": "old", "created_at": 20, "entities": existing[:1]},
        {"id": "recent", "created_at": 10, "entities": [recent]},
    ]

    selected = _seed_entities(incident, tickets, 10)

    assert selected[0] == recent
    assert selected[1:] == existing[:9]


def test_report_task_allows_context_and_all_run_one_citations() -> None:
    findings = sample()["findings"]
    task = make_report_task(
        INCIDENT_ID,
        attempt=2,
        findings=findings,
        incident={"id": INCIDENT_ID, "summary": None},
        assets=[],
        previous_artifact=None,
        asset_lookup_failed=True,
        context_evidence=("alt_01a19f93-1150-7000-8000-000000000004",),
    )

    assert task.output_contract == "incident_analysis"
    assert task.attempt == 2
    assert task.data["asset_lookup_failed"] is True
    assert task.allowed_evidence_ids == (
        "alt_01a19f93-1150-7000-8000-000000000004",
        "agl_01a19f93-1150-7000-8000-000000000009",
        "evt_01a19f93-1150-7000-8000-000000000005",
    )


def test_build_records_filters_unknown_technique_and_unions_evidence() -> None:
    data = sample()

    artifact, proposals, dropped = build_records(
        INCIDENT_ID,
        analysis_round=2,
        findings=data["findings"],
        analysis={
            **data["analysis"],
            "techniques": [
                *data["analysis"]["techniques"],
                {
                    "id": "T9999",
                    "evidence_ids": ["alt_01a19f93-1150-7000-8000-000000000004"],
                },
            ],
        },
        attack_names={"T1059.001": "PowerShell"},
        now_ms=1_793_678_580_000,
    )

    assert dropped == 1
    assert artifact["techniques"] == [
        {
            "id": "T1059.001",
            "name": "PowerShell",
            "evidence_ids": ["evt_01a19f93-1150-7000-8000-000000000005"],
        }
    ]
    assert artifact["evidence_ids"] == [
        "agl_01a19f93-1150-7000-8000-000000000009",
        "evt_01a19f93-1150-7000-8000-000000000005",
        "alt_01a19f93-1150-7000-8000-000000000004",
        "agl_01a19f93-1150-7000-8000-000000000010",
    ]
    assert [(item["kind"], item["seq"]) for item in proposals] == [
        ("detection_rule", 1),
        ("response_action", 1),
    ]


def test_only_transient_report_failures_are_retried() -> None:
    assert all(
        should_retry_report(value) for value in ("provider_error", "rate_limited", "log_error")
    )
    assert not any(
        should_retry_report(value)
        for value in ("format_error", "evidence_id_error", "budget_exceeded", "cancelled")
    )
