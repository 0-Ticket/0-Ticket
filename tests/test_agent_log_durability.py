"""Agent Log를 호출마다 쓰고, 시작 전 실패도 남기고, 저장 크기를 줄인다(#278).

가짜 모델과 메모리 기록기로 확인한다. 실제 DB는 test_agent_log_durability_db.py(db 마커)가 본다.
"""

import asyncio
import copy
import json
import logging
import threading
import time
from typing import Any

import psycopg
import pytest
from fake_model import FakeModel
from test_agent_core import CONFIG, REGISTRY, make_task, no_sleep
from tool_helpers import new_recorder

from soc.agent import AgentResult, run_agent
from soc.agent.agent_log import LogWriteError, MemoryLogSink, PostgresLogSink, jsonable
from soc.agent.runner import run_task
from soc.api.routes.hunts import summarize_runs
from soc.contracts import to_datetime, validate_contract
from soc.tools import Arg, ToolRegistry, ToolSpec

FAST_LOG = {"log_connect_timeout_seconds": 1, "log_statement_timeout_ms": 100}  # 마감 약 1.1초


def with_agent(**keys: Any) -> dict[str, Any]:
    return {**CONFIG, "agent": {**CONFIG["agent"], **keys}}


class RecordingSink(MemoryLogSink):
    """write 호출마다 넘어온 줄을 calls에 남긴다."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[dict[str, Any]]] = []

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.calls.append(list(rows))
        super().write(rows)


class FailFromSink(RecordingSink):
    """n번째 write부터 계속 실패한다(1이면 처음부터)."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n

    def write(self, rows: list[dict[str, Any]]) -> None:
        if len(self.calls) + 1 >= self.n:
            self.calls.append(list(rows))
            raise LogWriteError("connection to postgresql://soc:fake-db-pass@db.example.com failed")
        super().write(rows)


class FailFirstSink(RecordingSink):
    """처음 한 번만 실패한다."""

    def write(self, rows: list[dict[str, Any]]) -> None:
        if not self.calls:
            self.calls.append(list(rows))
            raise LogWriteError("first write failed")
        super().write(rows)


class StoreThenFailSink:
    """첫 write는 저장한 뒤 실패한다(커밋은 됐는데 응답을 못 받은 경우). 먼저 쓴 줄이 남는다."""

    def __init__(self) -> None:
        self.calls = 0
        self.stored: dict[tuple[str, int], dict[str, Any]] = {}
        self.attempts: dict[tuple[str, int], list[str]] = {}

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.calls += 1
        for row in rows:
            key = (row["run_id"], row["seq"])
            self.attempts.setdefault(key, []).append(json.dumps(row, sort_keys=True))
            self.stored.setdefault(key, row)  # ON CONFLICT DO NOTHING처럼 먼저 쓴 줄이 남는다
        if self.calls == 1:
            raise LogWriteError("lost ack")


class HangSink:
    """멈춘 DB를 흉내 낸다. 풀어 주기 전까지 write가 돌아오지 않는다."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.calls += 1
        self.release.wait(30)


def go(
    scenario: Any,
    sink: Any,
    *,
    task: Any = None,
    config: dict[str, Any] = CONFIG,
    registry: ToolRegistry = REGISTRY,
) -> tuple[AgentResult, FakeModel]:
    model = FakeModel(scenario)
    result = run_task(
        task or make_task(),
        model=model,
        model_name="fake-model",
        log_sink=sink,
        config=config,
        registry=registry,
        sleep=no_sleep,
    )
    return result, model


def lookup_spec(handler: Any) -> ToolSpec:
    return ToolSpec(
        name="lookup_alert",
        description="테스트용",
        handler=handler,
        bundle="test",
        result_kind="records",
        id_fields=("id",),
        args=(Arg("alert_id", "string", required=True), Arg("note", "string")),
    )


def db_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """메모리 기록기의 줄을 summarize_runs가 읽는 DB 행 모양으로 바꾼다."""
    return [
        {
            "run_id": r["run_id"],
            "seq": r["seq"],
            "kind": r["kind"],
            "outcome": r["outcome"],
            "tokens_in": r["tokens_in"],
            "tokens_out": r["tokens_out"],
            "started_at": to_datetime(r["started_at"]),
            "duration_ms": r["duration_ms"],
            "task": r["details"].get("task"),
            "attempt": r["details"].get("attempt"),
            "failure": r["details"].get("failure"),
            "validation": r["details"].get("validation"),
        }
        for r in sorted(rows, key=lambda r: (r["run_id"], r["seq"]))
    ]


class Killed(BaseException):
    """finalize까지 가지 못하고 프로세스가 죽는 것을 흉내 낸다."""


# C2: 호출이 끝날 때마다 쓴다


def test_rows_are_written_as_calls_finish() -> None:
    sink = RecordingSink()
    seen: dict[str, Any] = {}

    def peek(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        seen["kinds"] = [r["kind"] for r in sink.rows]
        return [{"id": args["alert_id"], "title": "x"}]

    result, _ = go("verdict_ok", sink, registry=ToolRegistry([lookup_spec(peek)]))
    assert result.ok is True
    # 도구가 도는 동안 도구 호출을 낸 model 줄은 이미 쓰였다
    assert seen["kinds"] == ["model"]
    assert [r["seq"] for r in sink.rows] == [1, 2, 3]


def test_final_answer_row_is_held_until_it_carries_validation() -> None:
    sink = RecordingSink()
    result, _ = go("verdict_ok", sink)
    assert result.ok is True
    assert [[r["kind"] for r in call] for call in sink.calls] == [["model"], ["tool"], ["model"]]
    final = sink.calls[-1][0]
    assert final["details"]["validation"] == "ok"
    assert "validation" not in sink.calls[0][0]["details"]


def test_write_failure_stops_writing_and_finalize_retries_once() -> None:
    sink = FailFirstSink()
    result, _ = go("verdict_ok", sink)
    assert result.ok is True
    assert len(sink.calls) == 2  # 첫 실패 뒤에는 훅이 더 쓰지 않고, finalize가 한 번 더 쓴다
    assert [r["seq"] for r in sink.rows] == [1, 2, 3]


def test_failing_retry_is_log_error_and_keeps_rows_already_written() -> None:
    sink = FailFromSink(2)  # 첫 줄은 쓰이고 그다음부터 실패한다
    result, _ = go("verdict_ok", sink)
    assert result.ok is False
    assert result.failure == "log_error"
    assert result.output is None
    assert len(sink.calls) == 3  # 첫 줄, 실패한 둘째 줄, finalize의 재시도
    assert [r["seq"] for r in sink.rows] == [1]
    assert "fake-db-pass" not in (result.detail or "")


def test_rewritten_rows_are_identical_to_the_first_write() -> None:
    sink = StoreThenFailSink()
    result, _ = go("verdict_ok", sink)
    assert result.ok is True
    assert len(sink.stored) == 3
    rewritten = [key for key, tries in sink.attempts.items() if len(tries) > 1]
    assert rewritten, "응답을 못 받은 줄을 finalize가 다시 쓴다"
    for key in rewritten:
        assert len(set(sink.attempts[key])) == 1  # 다시 쓰는 줄이 먼저 쓴 줄과 같다
    assert all(len(set(tries)) == 1 for tries in sink.attempts.values())


# C2: 이미 쓴 줄에는 failure를 붙이지 않고 종료 줄을 덧붙인다


def cancelled_registry() -> ToolRegistry:
    async def cancel(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        # 실행기의 종료처럼 이 루프의 모든 작업을 취소한다(SDK는 도구가 낸 CancelledError는 삼킨다)
        for task in asyncio.all_tasks():
            task.cancel()
        await asyncio.sleep(10)
        return []

    return ToolRegistry([lookup_spec(cancel)])


UNKNOWN_TOOL = {"steps": [{"tool_call": {"name": "no_such_tool", "arguments": {}}}]}


@pytest.mark.parametrize(
    ("name", "scenario", "registry", "failure"),
    [
        ("max_turns", "max_turns", REGISTRY, "budget_exceeded"),
        ("cancel_in_tool", "verdict_ok", None, "cancelled"),
        ("unknown_tool", UNKNOWN_TOOL, REGISTRY, "format_error"),
    ],
)
def test_failure_after_a_written_model_row_adds_an_unsent_closing_line(
    name: str, scenario: Any, registry: ToolRegistry | None, failure: str
) -> None:
    sink = RecordingSink()
    result, _ = go(scenario, sink, registry=registry or cancelled_registry())
    assert result.failure == failure
    rows = sink.rows
    for row in rows:
        validate_contract("agent_log", row)
    models = [r for r in rows if r["kind"] == "model"]
    closing = models[-1]
    assert closing["details"]["sent"] is False
    assert closing["details"]["failure"] == failure
    assert closing["outcome"] == "error"
    # 앞에 쓴 model 줄은 바뀌지 않는다: 끝났다는 표시가 없다
    written = models[-2]
    assert written["outcome"] == "ok"
    assert "failure" not in written["details"] and "validation" not in written["details"]
    # 끝난 run이라 summarize_runs가 error로 본다
    [summary] = summarize_runs(db_rows(rows))
    assert summary.outcome == "error"
    assert summary.failure == failure


def test_cancelled_tool_line_is_closed_as_error() -> None:
    sink = RecordingSink()
    go("verdict_ok", sink, registry=cancelled_registry())
    tool = next(r for r in sink.rows if r["kind"] == "tool")
    assert tool["outcome"] == "error"
    assert tool["details"]["failure"] == "cancelled"


def test_killed_run_is_incomplete() -> None:
    sink = RecordingSink()

    def kill(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        raise Killed

    with pytest.raises(Killed):
        go("verdict_ok", sink, registry=ToolRegistry([lookup_spec(kill)]))
    # 끝난 호출의 줄은 남고, 끝났다는 표시는 없다
    assert [r["kind"] for r in sink.rows] == ["model"]
    [summary] = summarize_runs(db_rows(sink.rows))
    assert summary.outcome == "incomplete"


# C2: 멈춘 DB


def test_hung_write_is_released_by_the_deadline_and_the_next_run_writes() -> None:
    hung = HangSink()
    start = time.monotonic()
    try:
        result, _ = go("verdict_ok", hung, config=with_agent(**FAST_LOG))
        elapsed = time.monotonic() - start
        assert result.ok is False
        assert result.failure == "log_error"
        assert elapsed < 8  # 훅과 finalize가 각각 마감(약 1.1초)에 풀린다
        writers = [t for t in threading.enumerate() if t.name == "agent-log-write"]
        assert writers and all(t.daemon for t in writers)  # 멈춘 쓰기가 프로세스 종료를 막지 않는다
        # 같은 프로세스의 다음 run은 DB가 정상이면 줄을 쓴다
        healthy = MemoryLogSink()
        again, _ = go("verdict_ok", healthy, config=with_agent(**FAST_LOG))
        assert again.ok is True
        assert [r["seq"] for r in healthy.rows] == [1, 2, 3]
    finally:
        hung.release.set()


def test_postgres_sink_passes_timeouts_and_keepalives(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_connect(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise psycopg.OperationalError("stop")

    monkeypatch.setattr("soc.agent.agent_log.psycopg.connect", fake_connect)
    with pytest.raises(LogWriteError):
        PostgresLogSink("postgresql://soc@127.0.0.1/soc").write([])
    assert seen["connect_timeout"] == 5
    assert "statement_timeout=5000" in seen["options"]
    assert seen["keepalives"] == 1
    assert seen["keepalives_idle"] == 10
    assert seen["keepalives_interval"] == 5
    assert seen["keepalives_count"] == 2
    assert seen["tcp_user_timeout"] == 10_000
    seen.clear()
    custom = PostgresLogSink(
        "postgresql://soc@127.0.0.1/soc", connect_timeout_seconds=2, statement_timeout_ms=300
    )
    with pytest.raises(LogWriteError):
        custom.write([])
    assert seen["connect_timeout"] == 2 and "statement_timeout=300" in seen["options"]


# C3: 시작 전 실패


def assert_one_unsent_line(
    sink: MemoryLogSink, result: AgentResult, failure: str
) -> dict[str, Any]:
    [row] = sink.rows
    validate_contract("agent_log", row)
    assert row["run_id"] == result.run_id  # 돌려준 run_id로 줄을 찾는다
    assert row["kind"] == "model" and row["outcome"] == "error"
    assert row["details"]["sent"] is False
    assert row["details"]["failure"] == failure
    assert row["tokens_in"] is None and row["tokens_out"] is None
    return row


def test_tool_config_error_leaves_a_line_with_the_returned_run_id() -> None:
    config = copy.deepcopy(CONFIG)
    config["tools"]["allowed"]["l1"] = ["no_such_tool"]
    sink = MemoryLogSink()
    result, _ = go("verdict_ok", sink, config=config)
    assert result.failure == "provider_error"
    row = assert_one_unsent_line(sink, result, "provider_error")
    assert isinstance(row["details"]["prompt_version"], str)  # 프롬프트는 만들어진 뒤다
    assert row["details"]["task"] == "l1_triage"


def test_prompt_failure_leaves_a_line_without_prompt_version() -> None:
    config = copy.deepcopy(CONFIG)
    del config["agent"]["l1"]["max_turns"]
    sink = MemoryLogSink()
    result, _ = go("verdict_ok", sink, config=config)
    assert result.failure == "provider_error"
    row = assert_one_unsent_line(sink, result, "provider_error")
    assert "prompt_version" not in row["details"]


def test_run_agent_without_llm_settings_leaves_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = MemoryLogSink()
    monkeypatch.setenv("DATABASE_URL", "postgresql://soc@127.0.0.1:1/soc")
    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", lambda *a, **k: sink)
    monkeypatch.setattr("soc.agent.runner.load_config", lambda: CONFIG)
    result = run_agent(make_task())
    assert result.failure == "provider_error"
    assert_one_unsent_line(sink, result, "provider_error")


def test_run_agent_config_failure_leaves_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = MemoryLogSink()
    monkeypatch.setenv("DATABASE_URL", "postgresql://soc@127.0.0.1:1/soc")
    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", lambda *a, **k: sink)

    def broken() -> dict[str, Any]:
        raise OSError("secret-looking path")

    monkeypatch.setattr("soc.agent.runner.load_config", broken)
    result = run_agent(make_task())
    assert result.failure == "provider_error"
    assert "secret-looking" not in (result.detail or "")
    assert_one_unsent_line(sink, result, "provider_error")


def test_run_agent_without_database_url_is_log_error_and_goes_to_the_runner_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("DATABASE_URL이 없으면 기록기를 만들지 않는다")

    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", never)
    with caplog.at_level(logging.WARNING, logger="soc.agent.runner"):
        result = run_agent(make_task())
    assert result.failure == "log_error"
    assert result.run_id.startswith("run_")
    assert "DATABASE_URL" in caplog.text  # 줄은 못 남기므로 실행기 로그로만 남는다
    assert "postgresql://" not in caplog.text


def test_unwritable_pre_start_failure_is_log_error_with_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://soc:fake-db-pass@127.0.0.1:1/soc")
    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", lambda *a, **k: FailFromSink(1))
    monkeypatch.setattr("soc.agent.runner.load_config", lambda: CONFIG)
    result = run_agent(make_task())
    assert result.failure == "log_error"
    assert (result.detail or "").endswith("; prior=provider_error")
    assert "fake-db-pass" not in (result.detail or "")


def test_usage_turns_do_not_count_lines_that_were_not_sent() -> None:
    l1 = {**CONFIG["agent"]["l1"], "max_input_chars": 10}
    sink = MemoryLogSink()
    result, model = go("verdict_ok", sink, config=with_agent(l1=l1))
    assert result.failure == "budget_exceeded"
    assert model.calls == []
    [row] = sink.rows
    assert row["details"]["sent"] is False
    assert result.usage["turns"] == 0


# C5: 저장 크기


def joined_inputs(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """model 줄의 입력을 run_id·seq 순으로 이어 붙여 호출마다의 전체 입력을 복원한다."""
    items: list[Any] = []
    out: list[list[Any]] = []
    for row in sorted(rows, key=lambda r: r["seq"]):
        if row["kind"] != "model" or row["details"].get("sent") is False:
            continue
        value = row["input"]
        items = (
            [*items[: value["input_from"]], *value["input"]]
            if "input_from" in value
            else list(value["input"])
        )
        out.append(items)
    return out


def test_model_rows_store_only_new_input_and_join_back() -> None:
    sink = MemoryLogSink()
    result, model = go("verdict_ok", sink)
    assert result.ok is True
    first, second = [r for r in sink.rows if r["kind"] == "model"]
    assert first["input"]["system"] == model.calls[0]["system"]
    assert "system" not in second["input"]  # system 지시는 첫 줄에만 있다
    assert second["input"]["input_from"] == len(first["input"]["input"])
    assert joined_inputs(sink.rows) == [jsonable(c["input"]) for c in model.calls]
    assert "input_reset" not in first["details"] and "input_reset" not in second["details"]


def test_format_error_retry_input_extends_the_previous_input_and_is_restored() -> None:
    sink = MemoryLogSink()
    result, model = go("format_error_then_ok", sink)
    assert result.ok is True
    inputs = [jsonable(c["input"]) for c in model.calls]
    assert inputs[1][: len(inputs[0])] == inputs[0]  # SDK의 재요청 입력은 앞 입력을 잇는다
    second = [r for r in sink.rows if r["kind"] == "model"][1]
    assert second["input"]["input_from"] == len(inputs[0])
    assert "input_reset" not in second["details"]
    assert joined_inputs(sink.rows) == inputs


def test_input_that_does_not_extend_the_previous_one_is_stored_whole_and_restored() -> None:
    first = [{"role": "user", "content": "a"}]
    second = [{"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}]
    recorder = new_recorder()

    async def calls() -> None:
        await recorder.on_llm_start(None, None, "system text", first)
        recorder._open.clear()  # 앞 호출은 끝난 것으로 본다(이 테스트는 입력 저장만 본다)
        await recorder.on_llm_start(None, None, "system text", second)

    asyncio.run(calls())
    row_1, row_2 = recorder.rows
    assert row_1["input"] == {"system": "system text", "input": first}
    assert row_2["input"] == {"input_from": 0, "input": second}
    assert row_2["details"]["input_reset"] is True
    assert joined_inputs(recorder.rows) == [first, second]


def big_records_registry() -> ToolRegistry:
    def handler(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        return [
            {"id": f"evt_01a19f93-1150-7000-8000-{i:012d}", "text": "x" * 1960} for i in range(100)
        ]

    spec = ToolSpec(
        name="big_records",
        description="테스트용",
        handler=handler,
        bundle="test",
        result_kind="records",
        id_fields=("id",),
    )
    return ToolRegistry([spec])


def l2_config() -> dict[str, Any]:
    config = copy.deepcopy(CONFIG)
    config["tools"]["allowed"]["l2"] = ["big_records"]
    return config


def l2_task() -> Any:
    return make_task(stage="l2", task="l2_investigate")


STEPS = [{"tool_call": {"name": "big_records", "arguments": {}}} for _ in range(13)]


def test_records_tool_line_stores_the_result_the_model_saw() -> None:
    sink = MemoryLogSink()
    go(
        {"steps": STEPS},
        sink,
        task=l2_task(),
        config=l2_config(),
        registry=big_records_registry(),
    )
    tools = [r for r in sink.rows if r["kind"] == "tool"]
    assert tools
    for row in tools:
        output = row["output"]
        assert output["call_id"] == row["id"]
        assert output["truncated"] is True
        assert output["omitted"] == 100 - len(output["records"]) > 0
        assert len(json.dumps(output, ensure_ascii=False)) <= 8_000 + 200  # 모델에게 보인 한도 안


def test_l2_max_scenario_stays_within_the_storage_ceiling() -> None:
    sink = MemoryLogSink()
    result, _ = go(
        {"steps": STEPS},
        sink,
        task=l2_task(),
        config=l2_config(),
        registry=big_records_registry(),
    )
    assert result.failure == "budget_exceeded"
    stored = sum(
        len(json.dumps(r["input"] if r["kind"] == "model" else r["output"], ensure_ascii=False))
        for r in sink.rows
    )
    assert stored <= 160_000
