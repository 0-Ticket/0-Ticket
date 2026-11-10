"""Agent Log를 실제 PostgreSQL에 호출마다 쓴다(db 마커, #278)."""

from typing import Any

import psycopg
import pytest
from fake_model import FakeModel
from test_agent_core import CONFIG, make_task, no_sleep
from test_agent_log_durability import lookup_spec

from soc.agent.agent_log import LogWriteError, MemoryLogSink, PostgresLogSink
from soc.agent.runner import run_task
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.tools import ToolRegistry

pytestmark = pytest.mark.db


@pytest.fixture
def migrated(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


def count(url: str) -> int:
    with psycopg.connect(url) as conn:
        (n,) = conn.execute("SELECT count(*) FROM agent_logs").fetchone()
    return n


def sample_rows() -> list[dict[str, Any]]:
    sink = MemoryLogSink()
    run_task(
        make_task(),
        model=FakeModel("verdict_ok"),
        model_name="fake-model",
        log_sink=sink,
        config=CONFIG,
        registry=ToolRegistry([lookup_spec(lambda args, ctx: [{"id": args["alert_id"]}])]),
        sleep=no_sleep,
    )
    return sink.rows


def test_rows_are_committed_while_the_run_is_going(migrated: str) -> None:
    seen: dict[str, int] = {}

    def peek(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        seen["during"] = count(migrated)  # 다른 연결로 읽는다. 커밋되지 않았으면 보이지 않는다
        return [{"id": args["alert_id"], "title": "x"}]

    result = run_task(
        make_task(),
        model=FakeModel("verdict_ok"),
        model_name="fake-model",
        log_sink=PostgresLogSink(migrated),
        config=CONFIG,
        registry=ToolRegistry([lookup_spec(peek)]),
        sleep=no_sleep,
    )
    assert result.ok is True
    assert seen["during"] == 1  # 도구 호출을 낸 model 줄
    assert count(migrated) == 3


def test_second_write_of_the_same_run_and_seq_keeps_the_first_row(migrated: str) -> None:
    rows = sample_rows()
    sink = PostgresLogSink(migrated)
    sink.write(rows[:1])
    sink.write([{**rows[0], "id": new_id("agl"), "name": "changed"}])  # 같은 (run_id, seq)
    sink.write(rows[:1])  # 같은 id
    assert count(migrated) == 1
    with psycopg.connect(migrated) as conn:
        assert conn.execute("SELECT name FROM agent_logs").fetchone() == ("fake-model",)


def test_a_batch_with_a_bad_line_is_all_or_nothing(migrated: str) -> None:
    rows = sample_rows()
    bad = {**rows[1], "seq": 0}  # seq >= 1 검사에 걸린다
    with pytest.raises(LogWriteError):
        PostgresLogSink(migrated).write([rows[0], bad])
    assert count(migrated) == 0
