"""Hunt 상세의 run 요약: 끝났다는 표시가 없는 run은 incomplete다(#278, D-036 읽는 규칙)."""

from datetime import UTC, datetime
from typing import Any

from soc.api.routes.hunts import summarize_runs

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def line(
    seq: int,
    kind: str = "model",
    outcome: str = "ok",
    *,
    run_id: str = "run_a",
    failure: str | None = None,
    validation: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "seq": seq,
        "kind": kind,
        "outcome": outcome,
        "tokens_in": 10 if kind == "model" else None,
        "tokens_out": 5 if kind == "model" else None,
        "started_at": T0,
        "duration_ms": 100,
        "task": "l3_verify",
        "attempt": 1,
        "failure": failure,
        "validation": validation,
    }


def outcomes(rows: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(run.outcome, run.failure) for run in summarize_runs(rows)]


def test_run_with_validation_on_its_last_model_line_is_ok() -> None:
    rows = [line(1), line(2, "tool"), line(3, validation="ok")]
    assert outcomes(rows) == [("ok", None)]


def test_run_without_a_closing_marker_is_incomplete() -> None:
    assert outcomes([line(1), line(2, "tool")]) == [("incomplete", None)]


def test_tool_failure_does_not_close_a_run() -> None:
    rows = [line(1), line(2, "tool", "error", failure="timeout")]
    assert outcomes(rows) == [("incomplete", None)]


def test_failure_on_a_model_line_closes_a_run_as_error() -> None:
    rows = [line(1), line(2, "tool"), line(3, outcome="error", failure="format_error")]
    assert outcomes(rows) == [("error", "format_error")]


def test_unsent_pre_start_line_is_a_finished_run() -> None:
    assert outcomes([line(1, outcome="error", failure="provider_error")]) == [
        ("error", "provider_error")
    ]


def test_runs_are_judged_one_by_one() -> None:
    rows = [
        line(1, run_id="run_a", validation="ok"),
        line(1, run_id="run_b"),
        line(1, run_id="run_c", outcome="error", failure="cancelled"),
    ]
    assert outcomes(rows) == [("ok", None), ("incomplete", None), ("error", "cancelled")]
