"""L3 마지막 시도: 끝났다는 표시가 없는 run은 시도가 아니다(db 마커, #278, D-036 읽는 규칙)."""

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from soc.agent.agent_log import PostgresLogSink
from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.l3.hunt import store

pytestmark = pytest.mark.db

NOW = to_datetime(1_800_000_000_000)


@pytest.fixture
def migrated(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


def l3_run(sink: PostgresLogSink, started: Any, lines: list[tuple[str, dict[str, Any]]]) -> None:
    """model 줄만 있는 l3_hypothesize run 하나를 쓴다. 줄은 (outcome, details)다."""
    run_id, subject_id = new_id("run"), new_id("hrn")
    rows = []
    for i, (outcome, details) in enumerate(lines, start=1):
        row = {
            "id": new_id("agl"),
            "run_id": run_id,
            "stage": "l3",
            "subject_type": "hunt",
            "subject_id": subject_id,
            "seq": i,
            "kind": "model",
            "name": "fake-model",
            "input": {},
            "output": None,
            "outcome": outcome,
            "tokens_in": None,
            "tokens_out": None,
            "started_at": to_epoch_ms(started) + i,
            "duration_ms": 0,
            "details": {"task": "l3_hypothesize", "attempt": 1, **details},
        }
        validate_contract("agent_log", row)
        rows.append(row)
    sink.write(rows)


def last_attempt(url: str) -> Any:
    with psycopg.connect(url) as conn:
        return store.last_attempt_started_at(conn, "l3_hypothesize")


def test_unfinished_runs_are_not_attempts(migrated: str) -> None:
    sink = PostgresLogSink(migrated)
    finished = NOW - timedelta(hours=3)
    pre_start = NOW - timedelta(hours=2)
    l3_run(sink, finished, [("ok", {"validation": "ok"})])
    l3_run(sink, pre_start, [("error", {"failure": "provider_error", "sent": False})])
    # 끝났다는 표시가 없는 run(강제 종료)과 cancelled run은 시도가 아니다
    l3_run(sink, NOW - timedelta(hours=1), [("ok", {})])
    l3_run(sink, NOW - timedelta(minutes=30), [("ok", {}), ("error", {"failure": "cancelled"})])

    # 시작 전 실패는 details.failure가 있어 시도로 센다
    assert abs(last_attempt(migrated) - pre_start) < timedelta(seconds=1)


def test_only_an_unfinished_run_means_no_attempt(migrated: str) -> None:
    l3_run(PostgresLogSink(migrated), NOW, [("ok", {})])
    assert last_attempt(migrated) is None
