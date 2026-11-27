"""L2 분류 워커는 DB와 분류 색인 설정을 읽는다."""

from typing import Any

import pytest

from soc.l2.analyze import worker as analyze_worker
from soc.l2.branch import worker
from soc.store.config import load_config as load_store_config


def config() -> dict[str, Any]:
    return {
        "l2": {
            "branch": {
                "candidate_window_ms": 1000,
                "max_candidates": 5,
                "max_incident_tickets": 10,
                "min_score": 0.7725,
                "max_calls_per_cycle": 3,
                "max_failures": 3,
                "failure_retry_delay_ms": 300_000,
            }
        },
        "store": load_store_config()["store"],
    }


def test_build_worker_reads_database_and_vector_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")

    built = worker.build_worker(config())

    assert built.stage == "l2"
    assert built.name == "l2_branch"


def test_build_analyze_worker_reads_shared_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    full = config()
    full["l2"]["analyze"] = {
        "lookback_ms": 1000,
        "max_failures": 3,
        "failure_retry_cooldown_ms": 3_600_000,
    }
    # 근거 발급(#382)은 발급용 siem_profile을 설정에서 읽는다
    full["tools"] = {
        "max_range_days": 7,
        "siem": {"evidence_siem_profile": "elk-evidence"},
    }
    full["asset_lookup"] = {"statement_timeout_ms": 5000}
    full["l3"] = {"intel": {"attack": {"version": "20.0"}}}
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")

    built = analyze_worker.build_worker(full)

    assert built.stage == "l2"
    assert built.name == "l2_analyze"


def test_build_analyze_worker_needs_the_evidence_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 발급분과 수집분을 가를 프로필이 없으면 조용히 섞이므로 시작 때 막는다(#382)
    full = config()
    full["l2"]["analyze"] = {
        "lookback_ms": 1000,
        "max_failures": 3,
        "failure_retry_cooldown_ms": 3_600_000,
    }
    full["tools"] = {"max_range_days": 7, "siem": {}}
    full["asset_lookup"] = {"statement_timeout_ms": 5000}
    full["l3"] = {"intel": {"attack": {"version": "20.0"}}}
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")

    with pytest.raises(ValueError, match="evidence_siem_profile"):
        analyze_worker.build_worker(full)
