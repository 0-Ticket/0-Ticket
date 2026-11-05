"""L2 Incident 분석의 근거 평탄화와 조회 구간을 확인한다."""

import json
from pathlib import Path

from soc.l2.analyze.context import calculate_window
from soc.l2.analyze.store import build_records
from soc.l2.analyze.tasks import analysis_citations, findings_citations, make_report_task
from soc.l2.analyze.worker import should_retry_report

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "analyze.json"
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


def test_window_is_clipped_and_reports_requested_start() -> None:
    window = calculate_window(
        earliest_ticket_ms=1_790_000_000_000,
        now_ms=1_800_000_000_000,
        lookback_ms=86_400_000,
        max_range_days=7,
    )

    assert window == {
        "from": 1_799_395_200_000,
        "to": 1_800_000_000_000,
        "truncated": True,
        "requested_from": 1_789_913_600_000,
    }


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
