"""Agent Log: 모델 호출·도구 호출 한 번이 한 줄이다(Agent Log 계약, #193).

LogRecorder가 SDK 훅으로 줄을 모으고, run_agent가 끝나기 전에 LogSink가 한 번에 쓴다.
DB 기록기는 한 트랜잭션으로 써서, 실패하면 그 실행의 줄이 하나도 남지 않는다.
"""

import json
import time
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
_INSERT = (
    f"INSERT INTO agent_logs ({', '.join(_COLUMNS)}) "  # 컬럼 이름은 상수다
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})"
)


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


class PostgresLogSink:
    """agent_logs 테이블에 한 트랜잭션으로 쓴다. 반환하면 커밋이 끝난 것이다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def write(self, rows: list[dict[str, Any]]) -> None:
        try:
            with psycopg.connect(self._database_url) as conn, conn.transaction():
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
        prompt_version: str,
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
        self._prompt_version = prompt_version
        self._open: dict[str, tuple[dict[str, Any], float]] = {}

    # 훅

    async def on_llm_start(self, context: Any, agent: Any, system_prompt: Any, input_items: Any):
        row = self._start(
            "model", self._model_name, {"system": system_prompt, "input": input_items}
        )
        row["details"]["prompt_version"] = self._prompt_version

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        row = self._finish("model", [jsonable(item) for item in response.output])
        if row is not None:
            row["tokens_in"] = int(response.usage.input_tokens)
            row["tokens_out"] = int(response.usage.output_tokens)

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        arguments = getattr(context, "tool_arguments", None)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError:
            parsed = arguments
        row = self._start("tool", tool.name, parsed if parsed is not None else {})
        self.tool_log_ids.append(row["id"])

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: object) -> None:
        self._finish("tool", jsonable(result))

    # 정리

    def finalize(self, failure: str | None, validation: str | None) -> list[dict[str, Any]]:
        """끝나지 않은 줄을 error로 닫고, 마지막 model 줄에 검증 결과와 실패를 남긴다."""
        for row, _ in self._open.values():
            row["outcome"] = "error"
            if failure is not None:
                row["details"]["failure"] = failure
        self._open.clear()
        models = [row for row in self.rows if row["kind"] == "model"]
        if models:
            last = models[-1]
            if validation is not None:
                last["details"]["validation"] = validation
            if failure is not None:
                last["outcome"] = "error"
                last["details"]["failure"] = failure
        return self.rows

    def _start(self, kind: str, name: str, value: Any) -> dict[str, Any]:
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
        self._open[kind] = (row, time.perf_counter())
        return row

    def _finish(self, kind: str, output: Any) -> dict[str, Any] | None:
        opened = self._open.pop(kind, None)
        if opened is None:
            return None
        row, started = opened
        row["output"] = None if output is None else output
        row["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return row


def jsonable(value: Any) -> Any:
    """SDK 객체(pydantic 모델 등)를 JSON 값으로 바꾼다."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=_default))


def _default(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return str(value)
