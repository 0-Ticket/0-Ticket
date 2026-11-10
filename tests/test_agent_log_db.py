"""Agent Log를 실제 agent_logs 테이블에 쓴다(db 마커, #209)."""

from typing import Any

import psycopg
import pytest
from fake_model import FakeModel
from test_agent_core import CONFIG, REGISTRY, make_task

from soc.agent.agent_log import PostgresLogSink
from soc.agent.runner import run_task
from soc.db.migrate import migrate

pytestmark = pytest.mark.db


@pytest.fixture
def migrated(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


def run_with_db(url: str, scenario: str) -> Any:
    return run_task(
        make_task(),
        model=FakeModel(scenario),
        model_name="fake-model",
        log_sink=PostgresLogSink(url),
        config=CONFIG,
        registry=REGISTRY,
    )


def fetch(url: str, run_id: str) -> list[tuple[Any, ...]]:
    # run_task가 끝난 뒤 새 연결로 읽는다. 커밋되지 않았으면 보이지 않는다.
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT seq, kind, name, outcome, tokens_in, tokens_out, output IS NULL,"
            " details FROM agent_logs WHERE run_id = %s ORDER BY seq",
            (run_id,),
        ).fetchall()


def test_ok_run_rows_are_committed(migrated: str) -> None:
    result = run_with_db(migrated, "verdict_ok")
    assert result.ok is True
    rows = fetch(migrated, result.run_id)
    assert [(r[0], r[1]) for r in rows] == [(1, "model"), (2, "tool"), (3, "model")]
    tool = rows[1]
    assert tool[4] is None and tool[5] is None
    assert rows[2][7]["validation"] == "ok"


def test_failed_run_rows_are_committed(migrated: str) -> None:
    result = run_with_db(migrated, "provider_error")
    assert result.failure == "provider_error"
    rows = fetch(migrated, result.run_id)
    last = rows[-1]
    assert last[1] == "model"
    assert last[3] == "error"
    assert last[6] is True  # 출력이 없으면 SQL NULL
    assert last[7]["failure"] == "provider_error"


def test_unreachable_database_is_log_error(migrated: str) -> None:
    bad = "postgresql://soc:fake-db-pass@127.0.0.1:1/soc?connect_timeout=1"
    result = run_task(
        make_task(),
        model=FakeModel("verdict_ok"),
        model_name="fake-model",
        log_sink=PostgresLogSink(bad),
        config=CONFIG,
        registry=REGISTRY,
    )
    assert result.ok is False
    assert result.failure == "log_error"
    assert "fake-db-pass" not in (result.detail or "")
    assert "127.0.0.1" not in (result.detail or "")


def test_partial_write_is_rolled_back(migrated: str) -> None:
    # 한 번에 쓰는 줄 묶음은 한 트랜잭션이다. 묶음의 마지막 줄이 seq >= 1 검사에 걸리면
    # 그 묶음의 줄은 하나도 남지 않는다. (같은 (run_id, seq)는 오류가 아니라 건너뛴다, #278)
    class Bad(PostgresLogSink):
        def write(self, rows: list[dict[str, Any]]) -> None:
            rows = [dict(r) for r in rows]
            rows[-1]["seq"] = 0
            super().write(rows)

    result = run_task(
        make_task(),
        model=FakeModel("verdict_ok"),
        model_name="fake-model",
        log_sink=Bad(migrated),
        config=CONFIG,
        registry=REGISTRY,
    )
    assert result.failure == "log_error"
    assert fetch(migrated, result.run_id) == []
