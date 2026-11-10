"""Agent Log: 모델 호출·도구 호출 한 번이 한 줄이다(Agent Log 계약, #193).

LogRecorder가 SDK 훅으로 줄을 모으고, 호출이 끝날 때마다 RowWriter가 그 줄을 바로 쓴다(#278).
도구 호출이 없는 최종 답 model 줄만 다음 호출이 시작되거나 finalize가 돌 때까지 보류한다.
그 줄에 validation·failure를 붙여야 하기 때문이다.

줄은 훅이 전달한 순간부터 내용을 고정한다. 이미 전달한 줄에는 validation·failure를 붙이지 않고,
붙일 수 없으면 sent=false 종료 줄을 덧붙인다. 읽는 규칙(D-036): 끝난 run에는 details.validation
또는 details.failure가 있는 model 줄이 있고, details.sent=false 줄은 모델에 보내지 않은 호출이다.
"""

import asyncio
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Protocol

import psycopg
from agents import RunHooks
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime
from soc.ids import new_id

_COLUMNS = (
    "id",
    "run_id",
    "stage",
    "subject_type",
    "subject_id",
    "seq",
    "kind",
    "name",
    "input",
    "output",
    "outcome",
    "tokens_in",
    "tokens_out",
    "started_at",
    "duration_ms",
    "details",
)
# 먼저 쓴 줄이 남는다. 응답을 못 받은 줄을 finalize가 다시 써도 중복되지 않는다(#278)
_INSERT = (
    f"INSERT INTO agent_logs ({', '.join(_COLUMNS)}) "  # 컬럼 이름은 상수다
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) ON CONFLICT DO NOTHING"
)

# 설정의 [agent] log_connect_timeout_seconds·log_statement_timeout_ms 기본값.
# 설정을 읽지 못할 때도 쓴다.
LOG_CONNECT_TIMEOUT_SECONDS = 5
LOG_STATEMENT_TIMEOUT_MS = 5000
# 마감 뒤에도 남는 쓰기 스레드의 연결을 닫기 위한 접속 인자(코드 고정값, 계획 278 "접속 인자").
# 상대 호스트가 사라진 경우에만 닫는다. tcp_user_timeout은 Linux에서만 적용된다.
_CONNECTION_GUARD: dict[str, int] = {
    "keepalives": 1,
    "keepalives_idle": 10,
    "keepalives_interval": 5,
    "keepalives_count": 2,
    "tcp_user_timeout": 10_000,
}


class LogWriteError(Exception):
    """Agent Log를 쓰지 못했다. 메시지에 DB 주소나 비밀 값을 넣지 않는다."""


class LogSink(Protocol):
    def write(self, rows: list[dict[str, Any]]) -> None: ...


class MemoryLogSink:
    """테스트용. 쓴 줄을 rows에 쌓는다."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)


def log_timeouts(config: dict[str, Any]) -> tuple[int, int]:
    """설정 [agent]의 (연결 시간 제한 초, 문장 시간 제한 ms). 없으면 기본값, 틀리면 ValueError."""
    agent = config.get("agent", {})
    connect = agent.get("log_connect_timeout_seconds", LOG_CONNECT_TIMEOUT_SECONDS)
    statement = agent.get("log_statement_timeout_ms", LOG_STATEMENT_TIMEOUT_MS)
    for value in (connect, statement):
        if type(value) is not int or value < 1:
            raise ValueError("Agent Log 시간 제한은 1 이상의 정수다")
    return connect, statement


class PostgresLogSink:
    """agent_logs 테이블에 한 트랜잭션으로 쓴다. 반환하면 커밋이 끝난 것이다.

    쓸 때마다 짧은 연결을 연다. 같은 (run_id, seq)나 id가 있으면 먼저 쓴 줄을 남기고 건너뛴다.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connect_timeout_seconds: int = LOG_CONNECT_TIMEOUT_SECONDS,
        statement_timeout_ms: int = LOG_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self._database_url = database_url
        self._connect_timeout = connect_timeout_seconds
        self._statement_timeout = statement_timeout_ms

    def write(self, rows: list[dict[str, Any]]) -> None:
        try:
            with (
                psycopg.connect(
                    self._database_url,
                    connect_timeout=self._connect_timeout,
                    options=f"-c statement_timeout={self._statement_timeout}",
                    **_CONNECTION_GUARD,
                ) as conn,
                conn.transaction(),
            ):
                for row in rows:
                    conn.execute(_INSERT, [_db_value(c, row[c]) for c in _COLUMNS])
        except psycopg.Error as exc:
            # 원래 예외 메시지에는 주소·값이 들어갈 수 있어 종류만 남긴다.
            raise LogWriteError(type(exc).__name__) from None


def _db_value(column: str, value: Any) -> Any:
    if column == "started_at":
        return to_datetime(value)
    if column == "output":
        return None if value is None else Jsonb(value)  # 출력이 없으면 SQL NULL
    if column in ("input", "details"):
        return Jsonb(value)
    return value


class RowWriter:
    """줄을 데몬 스레드로 쓰고, 마감 안에 못 쓰면 실패로 본다(#278).

    쓸 때마다 새 스레드를 만든다. 한 스레드가 얼어 있는 쓰기에 걸려도 다음 쓰기와 다음 run이
    그 뒤에 줄을 서지 않는다. 데몬이라 멈춘 쓰기가 프로세스 종료를 막지 않는다.
    첫 실패에서 훅의 쓰기를 멈추고(stopped), finalize가 안 쓴 줄을 한 번 더 시도한다(flush).
    prepare는 줄을 가리고 계약을 검사해 쓸 사본을 만든다.
    """

    def __init__(
        self,
        sink: LogSink,
        prepare: Callable[[dict[str, Any]], dict[str, Any]],
        deadline_seconds: float,
    ) -> None:
        self._sink = sink
        self._prepare = prepare
        self._deadline = deadline_seconds
        self.dispatched: set[str] = set()  # 전달한 줄의 id. 쓰였을 수 있어 내용을 바꾸지 않는다
        self._confirmed: set[str] = set()
        self.stopped = False

    async def write(self, row: dict[str, Any]) -> None:
        """훅에서 줄 하나를 쓴다. 실패하면 예외를 내지 않고 쓰기를 멈춘다."""
        if self.stopped:
            return
        self.dispatched.add(row["id"])
        try:
            future = self._spawn([self._prepare(row)])
            await asyncio.wait_for(asyncio.wrap_future(future), self._deadline)
        except Exception:  # 마감 초과(TimeoutError)·쓰기 실패·계약 검사 실패. 취소는 그대로 보낸다
            self.stopped = True
        else:
            self._confirmed.add(row["id"])

    def flush(self, rows: list[dict[str, Any]]) -> None:
        """아직 확인되지 않은 줄을 한 번에 쓴다. 실패하거나 마감을 넘기면 예외를 낸다."""
        pending = [row for row in rows if row["id"] not in self._confirmed]
        if not pending:
            return
        self.dispatched.update(row["id"] for row in pending)
        self._spawn([self._prepare(row) for row in pending]).result(timeout=self._deadline)
        self._confirmed.update(row["id"] for row in pending)

    def _spawn(self, rows: list[dict[str, Any]]) -> "Future[None]":
        future: Future[None] = Future()

        def work() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                self._sink.write(rows)
            except BaseException as exc:  # 스레드 밖에서 다시 낸다
                future.set_exception(exc)
            else:
                future.set_result(None)

        threading.Thread(target=work, name="agent-log-write", daemon=True).start()
        return future


class LogRecorder(RunHooks[Any]):
    """SDK 훅으로 모델·도구 호출을 한 줄씩 모은다. 병렬 도구 호출은 끄므로 순서대로 온다."""

    def __init__(
        self,
        *,
        run_id: str,
        stage: str,
        subject_type: str,
        subject_id: str,
        model_name: str,
        task: str,
        attempt: int,
        prompt_version: str | None,
        writer: RowWriter | None = None,
    ) -> None:
        self.rows: list[dict[str, Any]] = []
        self.tool_log_ids: list[str] = []
        self._base = {
            "run_id": run_id,
            "stage": stage,
            "subject_type": subject_type,
            "subject_id": subject_id,
        }
        self._model_name = model_name
        self._task = task
        self._attempt = attempt
        self._prompt_version = prompt_version  # 프롬프트를 만들기 전에 실패하면 None
        self._writer = writer
        self._held: dict[str, Any] | None = None
        self._prev_input: list[Any] | None = None  # 앞 model 호출의 입력(새로 더해진 항목만 저장)
        self._open: dict[str, tuple[dict[str, Any], float]] = {}
        # 열린 tool 줄. SDK의 tool_call_id별로 둔다(#211). 한 응답에 도구 호출이 여럿이어도
        # 줄이 섞이지 않는다. 빈·중복 tool_call_id의 줄은 _unmatched에 두고 ID를 주지 않는다.
        self._open_tools: dict[str, tuple[dict[str, Any], float]] = {}
        self._unmatched: list[tuple[dict[str, Any], float]] = []
        # 레지스트리가 결과를 알려 준 줄의 id. on_tool_end가 output을 덮어쓰지 않는다.
        self._reported: set[str] = set()

    # 훅

    async def on_llm_start(self, context: Any, agent: Any, system_prompt: Any, input_items: Any):
        await self._write_held()
        items = jsonable(input_items)
        previous = self._prev_input
        reset = False
        if not isinstance(items, list) or previous is None:
            value = {"system": system_prompt, "input": items}  # 첫 줄: system 지시와 입력 전체
        elif items[: len(previous)] == previous:
            value = {"input_from": len(previous), "input": items[len(previous) :]}
        else:  # 앞 입력의 접두가 아니면 전체를 저장한다
            value, reset = {"input_from": 0, "input": items}, True
        self._prev_input = items if isinstance(items, list) else None
        row = self._start("model", self._model_name, value)
        self._set_prompt_version(row)
        if reset:
            row["details"]["input_reset"] = True
        row["details"]["retries"] = 0  # 429 재시도 횟수. RetryingModel이 note_retry로 센다

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        row = self._finish("model", [jsonable(item) for item in response.output])
        if row is None:
            return
        row["tokens_in"] = int(response.usage.input_tokens)
        row["tokens_out"] = int(response.usage.output_tokens)
        if _calls_a_tool(row["output"]):
            await self._write(row)
        else:
            self._held = row  # 최종 답이다. 검증 결과를 붙인 뒤에 쓴다

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        arguments = getattr(context, "tool_arguments", None)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError:
            parsed = arguments
        row = self._new_row("tool", tool.name, parsed if parsed is not None else {})
        self.tool_log_ids.append(row["id"])
        call_id = getattr(context, "tool_call_id", None)
        opened = (row, time.perf_counter())
        if isinstance(call_id, str) and call_id and call_id not in self._open_tools:
            self._open_tools[call_id] = opened
        else:
            self._unmatched.append(opened)

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: object) -> None:
        call_id = getattr(context, "tool_call_id", None)
        opened = self._open_tools.pop(call_id, None) if isinstance(call_id, str) else None
        if opened is None:
            opened = next((o for o in self._unmatched if o[0]["name"] == tool.name), None)
            if opened is None:
                return
            self._unmatched.remove(opened)
        row, started = opened
        if row["id"] not in self._reported:
            row["output"] = jsonable(result)
        row["duration_ms"] = int((time.perf_counter() - started) * 1000)
        await self._write(row)

    # 도구 레지스트리가 부름(#211)

    def tool_log_id(self, tool_call_id: str) -> str | None:
        """열린 tool 줄의 id(agl_). 도구 결과의 call_id와 근거 장부 ID가 이 값이다."""
        opened = self._open_tools.get(tool_call_id)
        return opened[0]["id"] if opened is not None else None

    def report_tool(
        self,
        tool_call_id: str,
        output: Any,
        failure: str | None,
        blocked: bool,
        reason: str | None = None,
    ) -> None:
        """레지스트리가 알려 준 결과를 그 tool 줄에 남긴다.

        output은 모델에게 보인 결과다. records 도구는 모델에게 보인 본문(뺀 건수 포함, #278),
        오류면 모델에게 보낸 TOOL_ERROR 문구다. on_tool_end가 받는 값은 감싸서 자른 문자열이라
        쓰지 않는다. reason은 오류 코드보다 자세한 사유 이름(예: auth)이고 details.reason에
        쓴다(#212).
        """
        opened = self._open_tools.get(tool_call_id)
        if opened is None:
            return
        row = opened[0]
        row["output"] = None if output is None else jsonable(output)
        if failure is not None:
            row["outcome"] = "error"
            row["details"]["failure"] = failure
        if blocked:
            row["details"]["blocked"] = True
        if reason is not None:
            row["details"]["reason"] = reason
        self._reported.add(row["id"])

    # 래퍼·예산 필터가 부름

    def note_retry(self) -> None:
        """지금 열려 있는 model 줄의 429 재시도 횟수를 하나 늘린다."""
        opened = self._open.get("model")
        if opened is not None:
            opened[0]["details"]["retries"] += 1

    def add_budget_exceeded(self, chars: int, max_input_chars: int) -> None:
        """예산을 넘어 보내지 않은 호출을 model 줄 하나로 남긴다.

        SDK는 call_model_input_filter를 on_llm_start보다 먼저 부르므로 훅이 이 줄을 만들지 않는다.
        보내지 않은 내용은 넣지 않고 글자 수와 한도만 남긴다.
        """
        self.add_unsent("budget_exceeded", {"chars": chars, "max_input_chars": max_input_chars})

    def add_unsent(
        self, failure: str, value: Any = None, validation: str | None = None
    ) -> dict[str, Any]:
        """모델에 보내지 않은 호출·종료를 sent=false model 줄로 남긴다(#278).

        예산 초과, 시작 전 실패, 이미 쓴 줄에 failure를 붙일 수 없을 때의 종료 줄이 같은 모양이다.
        """
        row = self._new_row("model", self._model_name, {} if value is None else value)
        row["outcome"] = "error"
        self._set_prompt_version(row)
        row["details"]["sent"] = False
        row["details"]["failure"] = failure
        if validation is not None:
            row["details"]["validation"] = validation
        return row

    # 정리

    def finalize(self, failure: str | None, validation: str | None) -> list[dict[str, Any]]:
        """끝나지 않은 줄을 error로 닫고, 마지막 model 줄에 검증 결과와 실패를 남긴다.

        마지막 model 줄을 이미 전달했으면 그 줄은 바꾸지 않고 sent=false 종료 줄을 덧붙인다.
        """
        still_open = [*self._open.values(), *self._open_tools.values(), *self._unmatched]
        for row, _ in still_open:
            row["outcome"] = "error"
            if failure is not None:
                row["details"]["failure"] = failure
        self._open.clear()
        self._open_tools.clear()
        self._unmatched.clear()
        self._held = None  # rows에 있다. flush가 쓴다
        if failure is not None or validation is not None:
            models = [row for row in self.rows if row["kind"] == "model"]
            last = models[-1] if models else None
            if last is None or self._is_sent_to_log(last):
                if failure is not None:
                    self.add_unsent(failure, validation=validation)
            else:
                if validation is not None:
                    last["details"]["validation"] = validation
                if failure is not None:
                    last["outcome"] = "error"
                    last["details"]["failure"] = failure
        return self.rows

    def flush(self) -> None:
        """아직 쓰이지 않은 줄을 쓴다. 쓰지 못하면 예외를 낸다(실행은 log_error로 끝난다)."""
        if self._writer is not None:
            self._writer.flush(self.rows)

    # 안쪽

    async def _write(self, row: dict[str, Any]) -> None:
        if self._writer is not None:
            await self._writer.write(row)

    async def _write_held(self) -> None:
        held, self._held = self._held, None
        if held is not None:
            await self._write(held)

    def _is_sent_to_log(self, row: dict[str, Any]) -> bool:
        return self._writer is not None and row["id"] in self._writer.dispatched

    def _set_prompt_version(self, row: dict[str, Any]) -> None:
        if self._prompt_version is not None:
            row["details"]["prompt_version"] = self._prompt_version

    def _start(self, kind: str, name: str, value: Any) -> dict[str, Any]:
        row = self._new_row(kind, name, value)
        self._open[kind] = (row, time.perf_counter())
        return row

    def _new_row(self, kind: str, name: str, value: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": new_id("agl"),
            **self._base,
            "seq": len(self.rows) + 1,
            "kind": kind,
            "name": name,
            "input": jsonable(value),
            "output": None,
            "outcome": "ok",
            "tokens_in": None,
            "tokens_out": None,
            "started_at": time.time_ns() // 1_000_000,
            "duration_ms": 0,
            "details": {"task": self._task, "attempt": self._attempt},
        }
        self.rows.append(row)
        return row

    def _finish(self, kind: str, output: Any) -> dict[str, Any] | None:
        opened = self._open.pop(kind, None)
        if opened is None:
            return None
        row, started = opened
        row["output"] = None if output is None else output
        row["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return row


def _calls_a_tool(output: Any) -> bool:
    return isinstance(output, list) and any(
        isinstance(item, dict) and item.get("type") == "function_call" for item in output
    )


def jsonable(value: Any) -> Any:
    """SDK 객체(pydantic 모델 등)를 JSON 값으로 바꾼다."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=_default))


def _default(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return str(value)
