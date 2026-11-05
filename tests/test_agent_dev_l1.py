"""L1 실측용 시드와 작업 만들기(#215). DB 없이 본다."""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from soc.agent import AgentResult
from soc.agent.dev_l1 import (
    SEED_PATH,
    SEED_PROFILE,
    TASK_NAME,
    build_parser,
    build_rows,
    build_task,
    format_result,
    load_seed,
    main,
    task_prompt,
)
from soc.agent.types import contains_forbidden
from soc.contracts import validate_contract
from soc.l3.hunt.dev_seed import SEED_PROFILE as L3_SEED_PROFILE
from soc.l3.hunt.dev_seed import load_seed as load_l3_seed

FIXTURE = Path(__file__).parent / "fixtures" / "l1_e2e" / "dev_seed.json"
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
NOW_MS = 1_793_772_000_000  # 2026-11-04T06:00:00Z
DAY_MS = 86_400_000
ALERT_ID = "alt_01a19f93-1150-7000-8000-000000000004"


def _records(seed: dict) -> list[dict]:
    return [r for s in seed["scenarios"] for r in (s["alert"], *s["events"])]


def _values(value: object, key: str) -> list[str]:
    """ocsf 안의 key 값 전부."""
    if isinstance(value, dict):
        found = [v for k, v in value.items() if k == key and isinstance(v, str)]
        return found + [x for v in value.values() for x in _values(v, key)]
    if isinstance(value, list):
        return [x for v in value for x in _values(v, key)]
    return []


def _example_host(host: str) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in ("example.com", "example.net"))


def test_seed_path_points_at_the_hand_made_fixture() -> None:
    assert SEED_PATH.resolve() == FIXTURE.resolve()


def test_sample_uses_documentation_ips_and_example_domains() -> None:
    records = _records(load_seed())
    ips = [e["value"] for r in records for e in r["entities"] if e["type"] == "ip"]
    ips += [ip for r in records for ip in _values(r["ocsf"], "ip")]
    assert ips
    for ip in ips:
        assert any(ipaddress.ip_address(ip) in net for net in DOC_NETS), ip
    urls = [e["value"] for r in records for e in r["entities"] if e["type"] == "url"]
    domains = [e["value"] for r in records for e in r["entities"] if e["type"] == "domain"]
    assert urls and domains
    for host in [urlsplit(u).hostname or "" for u in urls] + domains:
        assert _example_host(host), host


def test_sample_has_two_scenarios_of_each_kind() -> None:
    seed = load_seed()
    kinds = [s["expected"] for s in seed["scenarios"]]
    assert sorted(kinds) == ["benign"] * 2 + ["malicious"] * 2 + ["undetermined"] * 2
    names = [s["name"] for s in seed["scenarios"]]
    assert len(set(names)) == 6
    for scenario in seed["scenarios"]:
        assert scenario["events"], scenario["name"]  # 도구로 찾을 Event가 있다


def test_sample_does_not_share_entities_with_l3_seed() -> None:
    """같은 개발 DB에 L3 시드가 있어도 모델이 다른 시나리오의 레코드를 근거로 들지 않게 한다."""
    l3 = load_l3_seed()
    l3_values = {
        e["value"]
        for s in l3["scenarios"]
        for r in (*s["alerts"], *s["events"])
        for e in r["entities"]
    }
    ours = {e["value"] for r in _records(load_seed()) for e in r["entities"]}
    assert ours.isdisjoint(l3_values)
    assert SEED_PROFILE != L3_SEED_PROFILE


def test_records_are_within_tool_range_days() -> None:
    """도구는 한 번에 max_range_days(기본 7일)까지 본다. 시나리오 하나는 그 안에 있다."""
    for scenario in load_seed()["scenarios"]:
        agos = [r["ago_ms"] for r in (scenario["alert"], *scenario["events"])]
        assert max(agos) - min(agos) < 7 * DAY_MS, scenario["name"]
        assert max(agos) < 7 * DAY_MS


def test_rows_pass_contracts_and_use_now() -> None:
    rows = build_rows(load_seed(), NOW_MS)
    assert len(rows.alerts) == 6
    assert len(rows.raw_records) == len(rows.alerts) + len(rows.events)
    for raw in rows.raw_records:
        validate_contract("raw_record", raw)
        assert raw["siem_profile"] == SEED_PROFILE
    refs = [raw["siem_ref"] for raw in rows.raw_records]
    assert len(set(refs)) == len(refs)
    for alert in rows.alerts:
        validate_contract("alert", alert)
        assert alert["triage"] is None
        assert alert["details"] == {}  # 시드 표시는 RawRecord에만 둔다
        assert NOW_MS - DAY_MS < alert["time"] < NOW_MS
    for event in rows.events:
        validate_contract("event", event)
        assert event["details"] == {}


def test_rows_get_new_ids_each_time() -> None:
    first = build_rows(load_seed(), NOW_MS)
    second = build_rows(load_seed(), NOW_MS)
    assert {a["id"] for a in first.alerts}.isdisjoint({a["id"] for a in second.alerts})


@pytest.mark.parametrize("ago", [0, -1, 1.5, True, "1"])
def test_bad_ago_ms_is_rejected(ago: object) -> None:
    seed = load_seed()
    seed["scenarios"][0]["alert"]["ago_ms"] = ago
    with pytest.raises(ValueError):
        build_rows(seed, NOW_MS)


def test_task_prompt_has_no_forbidden_phrase_and_stable_version() -> None:
    seed = load_seed()
    prompt = task_prompt(seed)
    assert not contains_forbidden(prompt.text)
    assert prompt.version == task_prompt(load_seed()).version
    assert re.fullmatch(r"[0-9a-f]{64}", prompt.version)


def test_build_task_is_l1_alert_verdict_task() -> None:
    alert = {"id": ALERT_ID, "time": NOW_MS, "severity": 3, "title": "t", "rule_id": None}
    alert["entities"] = []
    task = build_task(alert, task_prompt(load_seed()))
    assert (task.stage, task.task, task.output_contract) == ("l1", TASK_NAME, "verdict")
    assert (task.subject_type, task.subject_id) == ("alert", ALERT_ID)
    assert task.allowed_evidence_ids == (ALERT_ID,)
    assert task.data == {"alert": alert}
    assert list(task.cited_ids({"evidence_ids": ["evt_x"]})) == ["evt_x"]


def test_format_result_has_numbers_but_no_reason() -> None:
    result = AgentResult(
        ok=True,
        output={
            "decision": "malicious",
            "confidence": 0.9,
            "reason": "모델이 쓴 이유 본문",
            "evidence_ids": ["evt_a"],
            "decided_at": NOW_MS,
        },
        failure=None,
        detail=None,
        run_id="run_x",
        usage={"turns": 3, "tool_calls": 2, "tool_errors": 0, "tokens_in": 9000},
        cited_evidence_ids=["evt_a"],
    )
    line = format_result("malicious_powershell", "malicious", result)
    assert "모델이 쓴 이유" not in line
    for part in ("ok=True", "decision=malicious", "turns=3", "tokens_in=9000", "tokens_out=0"):
        assert part in line
    failed = AgentResult(
        ok=False, output=None, failure="budget_exceeded", detail="상세", run_id="run_y"
    )
    line = format_result("x", "benign", failed)
    assert "failure=budget_exceeded" in line and "decision=-" in line and "상세" not in line


def test_help_says_dev_db_only() -> None:
    assert "개발 DB 전용" in build_parser().format_help()


def test_main_without_database_url_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["seed"]) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_main_with_db_error_exits_one_without_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_url = "postgresql://user:hidden-password@127.0.0.1:1/nodb?connect_timeout=1"
    monkeypatch.setenv("DATABASE_URL", secret_url)
    assert main(["remove"]) == 1
    captured = capsys.readouterr()
    assert "DB 오류" in captured.err
    assert "hidden-password" not in captured.err + captured.out
