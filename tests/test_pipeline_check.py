"""활성화 파이프 준비 점검(#316). DB·네트워크 없이 가짜 점검 함수(Probes)로 본다."""

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from soc.agent.config import load_full_config
from soc.pipeline.check import Probes, format_check, run_checks

SECRET = "s3cr3t-marker-value"
NAMES = ["stages", "db", "migrations", "agent_db", "qdrant", "embedder", "llm", "tools_config"]
ENV = {
    "DATABASE_URL": f"postgresql://user:{SECRET}@db.example.com/soc",
    "AGENT_DATABASE_URL": f"postgresql://reader:{SECRET}@db.example.com/soc",
    "ELK_URL": "https://elk.example.com:9200",
    "ELK_API_KEY": SECRET,
    "QDRANT_URL": "http://qdrant.example.com:6333",
    "LLM_API_KEY": SECRET,
}


def noop(_config: dict[str, Any]) -> None:
    return None


def boom(_config: dict[str, Any]) -> None:
    raise RuntimeError(f"연결 실패 {SECRET}")


OK_PROBES = Probes(db=noop, migrations=noop, agent_db=noop, qdrant=noop, embedder=noop, llm=noop)


@pytest.fixture
def config(default_config_dir: Path) -> dict[str, Any]:
    return load_full_config(default_config_dir)


def by_name(checks: list[Any]) -> dict[str, Any]:
    return {c.name: c for c in checks}


def test_all_items_ok_with_working_probes(config: dict[str, Any]) -> None:
    checks = run_checks(config, OK_PROBES, ENV)
    assert [c.name for c in checks] == NAMES
    assert {c.status for c in checks} == {"OK"}
    assert format_check(checks[0]) == "OK   stages"


@pytest.mark.parametrize("name", ["db", "migrations", "agent_db", "qdrant", "embedder", "llm"])
def test_failing_probe_fails_only_its_item_and_runs_the_rest(
    config: dict[str, Any], name: str
) -> None:
    checks = by_name(run_checks(config, replace(OK_PROBES, **{name: boom}), ENV))
    assert checks[name].status == "FAIL" and checks[name].code == "RuntimeError"
    assert [n for n, c in checks.items() if c.status != "OK"] == [name]
    assert list(checks) == NAMES
    assert format_check(checks[name]) == f"FAIL {name} (RuntimeError)"


def test_output_never_carries_values(config: dict[str, Any]) -> None:
    config["llm"]["base_url"] = f"https://{SECRET}.example.com"
    probes = Probes(db=boom, migrations=boom, agent_db=boom, qdrant=boom, embedder=boom, llm=boom)
    lines = [format_check(c) for c in run_checks(config, probes, ENV)]
    assert len(lines) == len(NAMES)
    assert not [line for line in lines if SECRET in line or "example.com" in line]


@pytest.mark.parametrize(
    ("missing", "item"),
    [("DATABASE_URL", "db"), ("AGENT_DATABASE_URL", "agent_db")],
)
def test_missing_environment_variable_fails_without_probing(
    config: dict[str, Any], missing: str, item: str
) -> None:
    calls: list[str] = []

    def spy(_config: dict[str, Any]) -> None:
        calls.append(item)

    env = {k: v for k, v in ENV.items() if k != missing}
    checks = by_name(run_checks(config, replace(OK_PROBES, **{item: spy}), env))
    assert (checks[item].status, checks[item].code) == ("FAIL", "env_missing")
    assert calls == []


@pytest.mark.parametrize(("stage", "code"), [("l1", "l1_off"), ("l2", "l2_off")])
def test_stage_with_interval_zero_fails(config: dict[str, Any], stage: str, code: str) -> None:
    config["executor"][stage]["interval_seconds"] = 0
    check = by_name(run_checks(config, OK_PROBES, ENV))["stages"]
    assert (check.status, check.code) == ("FAIL", code)


def test_stage_without_workers_fails(config: dict[str, Any]) -> None:
    config["executor"]["l2"]["workers"] = []
    check = by_name(run_checks(config, OK_PROBES, ENV))["stages"]
    assert (check.status, check.code) == ("FAIL", "l2_off")


def test_qdrant_and_embedder_are_skipped_when_unused(config: dict[str, Any]) -> None:
    config["l2"]["branch"]["candidate_source"] = "recent"
    for stage in ("l1", "l2"):
        config["tools"]["allowed"][stage] = [
            t for t in config["tools"]["allowed"][stage] if t != "search_similar_cases"
        ]
    checks = by_name(run_checks(config, replace(OK_PROBES, qdrant=boom, embedder=boom), ENV))
    assert checks["qdrant"].status == checks["embedder"].status == "SKIP"
    assert format_check(checks["qdrant"]) == "SKIP qdrant"


def test_qdrant_is_checked_when_only_the_similar_tool_needs_it(config: dict[str, Any]) -> None:
    config["l2"]["branch"]["candidate_source"] = "recent"
    checks = by_name(run_checks(config, replace(OK_PROBES, qdrant=boom), ENV))
    assert checks["qdrant"].status == "FAIL"


def test_unknown_allowed_tool_fails(config: dict[str, Any]) -> None:
    config["tools"]["allowed"]["l1"].append("no_such_tool")
    check = by_name(run_checks(config, OK_PROBES, ENV))["tools_config"]
    assert (check.status, check.code) == ("FAIL", "unknown_tool")


def test_siem_environment_is_required_when_a_siem_tool_is_allowed(config: dict[str, Any]) -> None:
    env = {k: v for k, v in ENV.items() if k != "ELK_API_KEY"}
    check = by_name(run_checks(config, OK_PROBES, env))["tools_config"]
    assert (check.status, check.code) == ("FAIL", "siem_env")


def test_siem_environment_is_not_required_when_no_stage_allows_siem(
    config: dict[str, Any],
) -> None:
    for stage in ("l1", "l2"):
        config["tools"]["allowed"][stage] = [
            t for t in config["tools"]["allowed"][stage] if "siem" not in t
        ]
    env = {k: v for k, v in ENV.items() if not k.startswith("ELK_")}
    assert by_name(run_checks(config, OK_PROBES, env))["tools_config"].status == "OK"


def test_unreadable_ca_cert_fails(config: dict[str, Any], tmp_path: Path) -> None:
    config["tools"]["siem"]["ca_cert_path"] = str(tmp_path / "missing.pem")
    check = by_name(run_checks(config, OK_PROBES, ENV))["tools_config"]
    assert (check.status, check.code) == ("FAIL", "ca_cert")


def test_readable_ca_cert_passes(config: dict[str, Any]) -> None:
    pem = Path(__file__).parent / "fixtures" / "tls"
    cert = pem / "ca.pem"
    config["tools"]["siem"]["ca_cert_path"] = str(cert)
    assert by_name(run_checks(config, OK_PROBES, ENV))["tools_config"].status == "OK"


def test_run_checks_does_not_change_the_config(config: dict[str, Any]) -> None:
    before = copy.deepcopy(config)
    run_checks(config, OK_PROBES, ENV)
    assert config == before
