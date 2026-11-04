"""run_agent: 파이프가 부르는 단 하나의 접점(에이전트 구조, D-024).

처리 순서: 작업 검사(AgentTask를 만들 때) → 프롬프트 합성 → Runner.run_sync → JSON 파싱 →
decided_at 덮어쓰기 → validate_contract → 실패하면 1회 재요청 → 근거 장부 검사 → Agent Log 쓰기.
어떤 실패에도 예외를 밖으로 내지 않고 AgentResult를 돌려준다.
"""

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import openai
from agents import (
    Agent,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelSettings,
    RunConfig,
    Runner,
    set_tracing_disabled,
)
from agents.models.interface import Model

from soc.agent.agent_log import LogRecorder, LogSink, PostgresLogSink
from soc.agent.config import load_config
from soc.agent.redact import build_redactor
from soc.agent.types import AgentResult, AgentTask
from soc.contracts import ContractError, validate_contract
from soc.contracts.validate import _CONTRACTS
from soc.ids import new_id

BASE_PROMPT_PATH = Path(__file__).parent / "prompts" / "base.md"


class _Stop(Exception):
    """실행을 그 failure로 끝낸다. detail은 안전한 문장만 담는다."""

    def __init__(self, failure: str, detail: str, validation: str | None = None) -> None:
        super().__init__(detail)
        self.failure = failure
        self.detail = detail
        self.validation = validation


def run_agent(task: AgentTask) -> AgentResult:
    """설정의 모델과 DB 기록기로 작업 하나를 실행한다. 동기 함수다."""
    set_tracing_disabled(True)
    try:
        config = load_config()
    except Exception:
        return _failed("provider_error", "에이전트 설정을 읽지 못했다")
    model = _default_model(config)
    if model is None:
        return _failed("provider_error", "LLM 연결 설정이 없다")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return _failed("log_error", "환경변수 DATABASE_URL이 없다")
    return run_task(
        task,
        model=model,
        model_name=str(config["llm"].get("model", "")),
        log_sink=PostgresLogSink(database_url),
        config=config,
    )


def _default_model(config: dict[str, Any]) -> Model | None:
    """운영 모델. LLM 연결은 #210에서 붙인다."""
    return None


def run_task(
    task: AgentTask,
    *,
    model: Model,
    model_name: str,
    log_sink: LogSink,
    config: dict[str, Any],
    tools: Sequence[Any] = (),
) -> AgentResult:
    """run_agent의 본체. 테스트는 가짜 모델과 메모리 기록기를 넣는다."""
    set_tracing_disabled(True)  # 환경변수에 맡기지 않는다(docs/security.md)
    run_id = new_id("run")
    started = time.perf_counter()
    instructions = compose_instructions(task)
    recorder = LogRecorder(
        run_id=run_id,
        stage=task.stage,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        model_name=model_name or "unknown",
        task=task.task,
        attempt=task.attempt,
        prompt_version=hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
    )

    output: Any = None
    cited: list[str] = []
    failure: str | None = None
    detail: str | None = None
    validation: str | None = None
    try:
        output, cited = _execute(task, model, instructions, recorder, config, tools)
        validation = "ok"
    except _Stop as stop:
        failure, detail, validation = stop.failure, stop.detail, stop.validation
    except asyncio.CancelledError:
        failure, detail = "cancelled", "실행이 중단됐다"
    except Exception as exc:  # 어떤 실패도 밖으로 내지 않는다. 메시지는 감춘다
        failure, detail = "provider_error", f"예상하지 못한 오류({type(exc).__name__})"

    rows = recorder.finalize(failure, validation)
    try:
        redact = build_redactor(config)
        rows = [_redacted(row, redact) for row in rows]
        for row in rows:
            validate_contract("agent_log", row)
        log_sink.write(rows)
    except Exception as exc:
        failure, detail = "log_error", f"Agent Log를 쓰지 못했다({type(exc).__name__})"

    ok = failure is None
    return AgentResult(
        ok=ok,
        output=output if ok else None,
        failure=failure,  # type: ignore[arg-type]
        detail=detail,
        run_id=run_id,
        usage=_usage(recorder.rows, started),
        cited_evidence_ids=cited if ok else [],
    )


def compose_instructions(task: AgentTask) -> str:
    """1층(base.md)과 4층(작업 프롬프트). 2·3·5층은 #210에서 더한다."""
    base = BASE_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return f"{base}\n\n{task.prompt.text.strip()}"


def wrap_data(data: Any) -> str:
    """입력 데이터를 구분자로 감싼다. 데이터 속 '<'는 \\u003c로 바꿔 구분자를 닫지 못하게 한다."""
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<data>\n{payload}\n</data>"


def _execute(
    task: AgentTask,
    model: Model,
    instructions: str,
    recorder: LogRecorder,
    config: dict[str, Any],
    tools: Sequence[Any],
) -> tuple[Any, list[str]]:
    max_turns = int(config["agent"][task.stage]["max_turns"])
    agent = Agent(
        name=f"soc-{task.stage}",
        instructions=instructions,
        model=model,
        tools=list(tools),
        model_settings=ModelSettings(parallel_tool_calls=False),
    )
    run_config = RunConfig(tracing_disabled=True)

    def run(items: list[Any], turns: int) -> Any:
        try:
            return Runner.run_sync(
                agent, items, max_turns=turns, hooks=recorder, run_config=run_config
            )
        except MaxTurnsExceeded:
            raise _Stop("budget_exceeded", "max_turns를 넘었다") from None
        except openai.RateLimitError:
            raise _Stop("rate_limited", "LLM 호출 한도를 넘었다(429)") from None
        except openai.OpenAIError as exc:
            raise _Stop("provider_error", f"LLM 호출 실패({type(exc).__name__})") from None
        except ModelBehaviorError:
            raise _Stop("format_error", "모델이 허용되지 않은 형식으로 답했다") from None

    result = run([{"role": "user", "content": wrap_data(task.data)}], max_turns)
    used = len(result.raw_responses)
    output, violation = _check_output(task, result.final_output)
    if violation is not None:
        remaining = max_turns - used
        if remaining <= 0:
            raise _Stop("budget_exceeded", "형식 오류 재요청에 남은 턴이 없다", "format_error")
        retry = result.to_input_list() + [{"role": "user", "content": f"형식 오류: {violation}"}]
        result = run(retry, remaining)
        output, violation = _check_output(task, result.final_output)
        if violation is not None:
            raise _Stop("format_error", f"재요청 뒤에도 계약 위반: {violation}", "format_error")

    ledger = set(task.allowed_evidence_ids) | set(recorder.tool_log_ids)
    try:
        cited = list(dict.fromkeys(task.cited_ids(output)))
    except Exception:
        raise _Stop(
            "evidence_id_error", "출력에서 근거 ID를 꺼내지 못했다", "evidence_id_error"
        ) from None
    if any(not isinstance(i, str) or i not in ledger for i in cited):
        raise _Stop("evidence_id_error", "근거 장부에 없는 ID를 인용했다", "evidence_id_error")
    return output, cited


def _check_output(task: AgentTask, final_output: Any) -> tuple[Any, str | None]:
    """(출력, 위반 설명). 위반 설명에는 경로와 규칙만 담고 값은 담지 않는다."""
    if not isinstance(final_output, str):
        return None, "(root): json"
    try:
        data = json.loads(final_output)
    except ValueError:
        return None, "(root): json"
    if isinstance(data, dict) and _has_top_level(task.output_contract, "decided_at"):
        data["decided_at"] = time.time_ns() // 1_000_000  # 모델이 낸 시각은 쓰지 않는다
    try:
        validate_contract(task.output_contract, data)
    except ContractError as exc:
        return None, ", ".join(f"{v.path}: {v.rule}" for v in exc.violations)
    return data, None


def _has_top_level(contract: str, field: str) -> bool:
    model = _CONTRACTS[contract][1]
    return field in model.model_fields


def _redacted(row: dict[str, Any], redact: Any) -> dict[str, Any]:
    out = dict(row)
    for key in ("input", "output", "details"):
        out[key] = redact(row[key])
    return out


def _usage(rows: list[dict[str, Any]], started: float) -> dict[str, int]:
    models = [r for r in rows if r["kind"] == "model"]
    return {
        "turns": len(models),
        "tool_calls": sum(1 for r in rows if r["kind"] == "tool"),
        "tool_errors": 0,  # 도구 오류 문구는 도구 레지스트리(#211)가 만든다
        "tokens_in": sum(r["tokens_in"] or 0 for r in models),
        "tokens_out": sum(r["tokens_out"] or 0 for r in models),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _failed(failure: str, detail: str) -> AgentResult:
    return AgentResult(
        ok=False,
        output=None,
        failure=failure,
        detail=detail,
        run_id=new_id("run"),  # type: ignore[arg-type]
    )
