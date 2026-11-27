"""L2 Incident 분석의 근거 평탄화와 조회 구간을 확인한다."""

import json
from pathlib import Path

from soc.contracts import validate_contract
from soc.l2.analyze.context import calculate_window
from soc.l2.analyze.store import build_records
from soc.l2.analyze.tasks import (
    analysis_citations,
    findings_citations,
    make_investigate_task,
    make_report_task,
)
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


def test_window_covers_old_evidence_without_tool_range_floor() -> None:
    window = calculate_window(
        earliest_ms=1_790_000_000_000,
        now_ms=1_800_000_000_000,
        lookback_ms=259_200_000,
    )

    assert window == {"from": 1_789_740_800_000, "to": 1_800_000_000_000}


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
        ("detection", 1),
        ("response", 2),
    ]
    assert proposals[0]["detail"] == "의심 요청 뒤 자식 프로세스 실행을 탐지한다"
    assert (proposals[0]["priority"], proposals[0]["title"]) == ("high", "자식 프로세스 실행 탐지")
    assert proposals[0]["rationale"] == "요청 직후 웹 서버가 프로세스를 실행했다"
    for proposal in proposals:
        validate_contract("incident_proposal", proposal)


def test_build_records_keeps_model_order_across_kinds_and_cleans_titles() -> None:
    data = sample()
    first, second = data["analysis"]["recommendations"]
    analysis = {
        **data["analysis"],
        "recommendations": [
            {**second, "title": " 서버 \n  점검\u3000필요 "},
            first,
            {**second, "title": "두 번째 대응"},
        ],
    }

    _, proposals, _ = build_records(
        INCIDENT_ID,
        analysis_round=1,
        findings=data["findings"],
        analysis=analysis,
        attack_names={"T1059.001": "PowerShell"},
        now_ms=1_793_678_580_000,
    )

    assert [(item["seq"], item["kind"], item["title"]) for item in proposals] == [
        (1, "response", "서버 점검 필요"),
        (2, "detection", "자식 프로세스 실행 탐지"),
        (3, "response", "두 번째 대응"),
    ]


def test_build_records_without_recommendations_makes_no_proposals() -> None:
    data = sample()

    _, proposals, _ = build_records(
        INCIDENT_ID,
        analysis_round=1,
        findings=data["findings"],
        analysis={**data["analysis"], "recommendations": []},
        attack_names={},
        now_ms=1_793_678_580_000,
    )

    assert proposals == []


def test_report_prompt_states_title_summary_impact_and_recommendation_rules() -> None:
    task = make_report_task(
        INCIDENT_ID,
        attempt=1,
        findings=sample()["findings"],
        incident={"id": INCIDENT_ID, "summary": None},
        assets=[],
        previous_artifact=None,
        asset_lookup_failed=False,
        context_evidence=(),
    )
    text = task.prompt.text

    for expected in (
        "title",  # 제목 규칙
        "공격 유형",
        "ID나 룰 코드만",
        "무엇이, 언제, 어디서, 어떻게",  # 사건 요약
        "영향받은 자산",  # 영향
        "recommendations",
        "response",
        "detection",
        "high",
        "rationale",  # 근거 작성 규칙
        "최대 10개",
        "200자",
        "2000자",
        "1000자",
        "data.evidence",  # 발급 근거 발췌(#382): 인용 방법과 데이터로만 읽기
        "evidence_id",
        "데이터로만 읽는다",
        "따르지 않는다",
        "evidence_omitted",
    ):
        assert expected in text, expected
    assert "detection_rules" not in text
    assert "response_actions" not in text


def test_report_input_drops_siem_refs_but_leaves_the_findings_object_alone() -> None:
    findings = {**sample()["findings"], "siem_refs": ["idx/dropped-doc"]}
    task = make_report_task(
        INCIDENT_ID,
        attempt=1,
        findings=findings,
        incident={"id": INCIDENT_ID, "summary": None},
        assets=[],
        previous_artifact=None,
        asset_lookup_failed=False,
        context_evidence=(),
    )

    assert "siem_refs" not in task.data["findings"]
    assert "dropped-doc" not in json.dumps(task.data)
    assert findings["siem_refs"] == ["idx/dropped-doc"]  # 원본은 그대로다
    assert task.data["findings"]["timeline"] == findings["timeline"]


def test_only_transient_report_failures_are_retried() -> None:
    assert all(
        should_retry_report(value) for value in ("provider_error", "rate_limited", "log_error")
    )
    assert not any(
        should_retry_report(value)
        for value in ("format_error", "evidence_id_error", "budget_exceeded", "cancelled")
    )


def test_investigate_prompt_treats_the_rejection_as_data_and_report_prompt_is_unchanged() -> None:
    investigate = make_investigate_task(
        INCIDENT_ID, attempt=1, data={}, allowed_evidence_ids=()
    ).prompt.text
    report = make_report_task(
        INCIDENT_ID,
        attempt=1,
        findings=sample()["findings"],
        incident={"id": INCIDENT_ID, "summary": None},
        assets=[],
        previous_artifact=None,
        asset_lookup_failed=False,
        context_evidence=(),
    ).prompt.text

    for expected in ("data.rejection", "반려", "지시가 아니", "reason", "null", "도구 결과"):
        assert expected in investigate, expected
    assert "rejection" not in report
