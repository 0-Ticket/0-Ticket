"""L2 분류 워커는 외부 저장소 없이 그래프 분류를 준비한다."""

from typing import Any

import pytest

from soc.l2.analyze import worker as analyze_worker
from soc.l2.branch import worker


def config() -> dict[str, Any]:
    return {
        "l2": {
            "branch": {
                "candidate_window_ms": 1000,
                "max_candidates": 5,
            }
        },
    }


def test_build_worker_needs_only_database_and_graph_limits(monkeypatch: pytest.MonkeyPatch) -> None:
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
    full["tools"] = {"max_range_days": 7}
    full["asset_lookup"] = {"statement_timeout_ms": 5000}
    full["l3"] = {"intel": {"attack": {"version": "20.0"}}}
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")

    built = analyze_worker.build_worker(full)

    assert built.stage == "l2"
    assert built.name == "l2_analyze"
