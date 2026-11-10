"""run_agent: 파이프가 부르는 단 하나의 접점(에이전트 구조, D-024).

처리 순서: 작업 검사(AgentTask를 만들 때) → 프롬프트 5층 합성 → Runner.run_sync → JSON 파싱 →
decided_at 덮어쓰기 → validate_contract → 실패하면 1회 재요청 → 근거 장부 검사.
Agent Log는 호출이 끝날 때마다 쓰고, 끝나면 안 쓴 줄을 마저 쓴다(#278). 실행 시작 전에 실패해도
sent=false 줄을 남긴다. 모델 호출마다 입력 예산(call_model_input_filter)을 검사하고,
429는 RetryingModel이 다시 부른다.
도구는 레지스트리(soc.tools)가 stage의 허용 목록에 있는 것만 붙인다(#211).
어떤 실패에도 예외를 밖으로 내지 않고 AgentResult를 돌려준다.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
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
from agents.run_config import CallModelData, ModelInputData
from openai.types.shared import Reasoning

from soc.agent.agent_log import (
    LogRecorder,
    LogSink,
    PostgresLogSink,
    RowWriter,
    log_timeouts,
)
from soc.agent.compose import compose_instructions, has_top_level_field
from soc.agent.config import load_config
from soc.agent.llm import LLMConfigError, RetryingModel, Sleep, build_model, input_chars
from soc.agent.redact import build_redactor
from soc.agent.types import AgentResult, AgentTask
from soc.contracts import ContractError, validate_contract
from soc.ids import new_id
from soc.tools import ToolConfigError, ToolRegistry, ToolSession, default_registry

logger = logging.getLogger(__name__)


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
    run_id = new_id("run")  # 시작 전에 실패해도 이 run_id의 줄을 남긴다
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        # 줄을 쓸 곳이 없다. 실행기 로그로만 남긴다.
        logger.warning("환경변수 DATABASE_URL이 없어 Agent Log를 쓰지 못한다(run=%s)", run_id)
        return _failed("log_error", "환경변수 DATABASE_URL이 없다", run_id)
    try:
        config = load_config()
    except Exception:
        sink = PostgresLogSink(database_url)
        return _before_start(
            task, run_id, sink, {}, "provider_error", "에이전트 설정을 읽지 못했다"
        )
    sink = _postgres_sink(database_url, config)
    try:
        model, model_name = build_model(config)
    except LLMConfigError as exc:
        return _before_start(task, run_id, sink, config, "provider_error", str(exc))  # 주소·키 없음
    except Exception as exc:
        detail = f"LLM 연결을 만들지 못했다({type(exc).__name__})"
        return _before_start(task, run_id, sink, config, "provider_error", detail)
    return run_task(
        task,
        model=model,
        model_name=model_name,
        log_sink=sink,
        config=config,
        run_id=run_id,
    )


def run_task(
    task: AgentTask,
    *,
    model: Model,
    model_name: str,
    log_sink: LogSink,
    config: dict[str, Any],
    registry: ToolRegistry | None = None,
    sleep: Sleep = asyncio.sleep,
    run_id: str | None = None,
) -> AgentResult:
    """run_agent의 본체. 테스트는 가짜 모델과 메모리 기록기, 기다리지 않는 sleep을 넣는다.

    도구는 registry(기본: 운영 레지스트리)에서 stage의 허용 목록([tools.allowed])에 있는 것만
    붙는다. 테스트의 가짜 도구도 ToolSpec으로 만들어 ToolRegistry에 넣고 여기로 넘긴다.
    run_id를 받으면 그 값을 쓴다(run_agent가 시작 전 실패의 줄과 같은 값을 쓰려고 넘긴다).
    """
    set_tracing_disabled(True)  # 환경변수에 맡기지 않는다(docs/security.md)
    run_id = run_id or new_id("run")
    started = time.perf_counter()
    try:
        writer = _writer(log_sink, config)
    except Exception:  # [agent]의 Agent Log 시간 제한이 틀렸다
        detail = "Agent Log 설정이 잘못됐다"
        return _before_start(task, run_id, log_sink, {}, "provider_error", detail, model_name)
    try:
        max_turns = int(config["agent"][task.stage]["max_turns"])
        instructions = compose_instructions(task, max_turns=max_turns)
    except Exception as exc:  # 설정·프롬프트 파일 문제. 예외는 밖으로 내지 않는다
        detail = f"프롬프트를 만들지 못했다({type(exc).__name__})"
        return _before_start(task, run_id, log_sink, config, "provider_error", detail, model_name)
    recorder = LogRecorder(
        run_id=run_id,
        stage=task.stage,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        model_name=model_name or "unknown",
        task=task.task,
        attempt=task.attempt,
        prompt_version=hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        writer=writer,
    )
    try:
        tools = (registry or default_registry()).session(
            stage=task.stage, config=config, recorder=recorder
        )
    except ToolConfigError:
        detail = "도구 설정 오류(허용 목록이나 도구 결과 한도)"
        return _stop_before_start(recorder, run_id, "provider_error", detail)

    output: Any = None
    cited: list[str] = []
    failure: str | None = None
    detail: str | None = None
    validation: str | None = None
    try:
        output, cited = _execute(task, model, instructions, recorder, config, tools, sleep)
        validation = "ok"
    except _Stop as stop:
        failure, detail, validation = stop.failure, stop.detail, stop.validation
    except asyncio.CancelledError:
        failure, detail = "cancelled", "실행이 중단됐다"
    except Exception as exc:  # 어떤 실패도 밖으로 내지 않는다. 메시지는 감춘다
        failure, detail = "provider_error", f"예상하지 못한 오류({type(exc).__name__})"

    failure, detail = _seal(recorder, run_id, failure, detail, validation)

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


def _postgres_sink(database_url: str, config: dict[str, Any]) -> PostgresLogSink:
    try:
        connect, statement = log_timeouts(config)
    except ValueError:  # run_task가 같은 설정 오류를 실패로 알린다
        return PostgresLogSink(database_url)
    return PostgresLogSink(
        database_url, connect_timeout_seconds=connect, statement_timeout_ms=statement
    )


def _writer(sink: LogSink, config: dict[str, Any]) -> RowWriter:
    """줄을 쓰기 직전에 가리고 계약을 검사하는 쓰기 도구. 마감은 연결 + 문장 시간 제한이다."""
    connect, statement = log_timeouts(config)
    redact = build_redactor(config)

    def prepare(row: dict[str, Any]) -> dict[str, Any]:
        out = _redacted(row, redact)
        validate_contract("agent_log", out)
        return out

    return RowWriter(sink, prepare, connect + statement / 1000)


def _seal(
    recorder: LogRecorder,
    run_id: str,
    failure: str | None,
    detail: str | None,
    validation: str | None,
) -> tuple[str | None, str | None]:
    """실행을 닫고 안 쓴 줄을 마저 쓴다. 쓰지 못하면 log_error로 바꾼다."""
    recorder.finalize(failure, validation)
    try:
        recorder.flush()
    except Exception as exc:
        # 앞의 실패를 덮을 때는 그 종류만 남긴다. DB 주소·비밀 값·예외 메시지는 넣지 않는다.
        logger.warning("Agent Log를 쓰지 못했다(run=%s, %s)", run_id, type(exc).__name__)
        prior = f"; prior={failure}" if failure is not None else ""
        return "log_error", f"Agent Log를 쓰지 못했다({type(exc).__name__}){prior}"
    return failure, detail


def _before_start(
    task: AgentTask,
    run_id: str,
    sink: LogSink,
    config: dict[str, Any],
    failure: str,
    detail: str,
    model_name: str | None = None,
) -> AgentResult:
    """프롬프트를 만들기 전에 끝난 실행의 sent=false 줄을 남기고 결과를 돌려준다."""
    try:
        writer = _writer(sink, config)
    except Exception:
        writer = _writer(sink, {})  # 시간 제한 설정이 틀렸으면 코드 기본값으로 쓴다
    recorder = LogRecorder(
        run_id=run_id,
        stage=task.stage,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        model_name=model_name or "unknown",
        task=task.task,
        attempt=task.attempt,
        prompt_version=None,
        writer=writer,
    )
    return _stop_before_start(recorder, run_id, failure, detail)


def _stop_before_start(
    recorder: LogRecorder, run_id: str, failure: str, detail: str
) -> AgentResult:
    recorder.add_unsent(failure)
    sealed_failure, sealed_detail = _seal(recorder, run_id, failure, detail, None)
    return AgentResult(
        ok=False,
        output=None,
        failure=sealed_failure,  # type: ignore[arg-type]
        detail=sealed_detail,
        run_id=run_id,  # type: ignore[arg-type]
    )


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
    tools: ToolSession,
    sleep: Sleep,
) -> tuple[Any, list[str]]:
    stage = config["agent"][task.stage]
    max_turns = int(stage["max_turns"])
    max_input_chars = int(stage["max_input_chars"])
    agent = Agent(
        name=f"soc-{task.stage}",
        instructions=instructions,
        model=RetryingModel(
            model,
            retries=int(config["llm"]["rate_limit_retries"]),
            sleep=sleep,
            on_retry=recorder.note_retry,
        ),
        tools=list(tools.function_tools()),
        # retry는 켜지 않는다(None). 재시도는 RetryingModel 하나만 한다.
        model_settings=ModelSettings(
            parallel_tool_calls=False,
            reasoning=Reasoning(effort=stage["reasoning_effort"]),
        ),
    )

    def check_budget(data: CallModelData[Any]) -> ModelInputData:
        chars = input_chars(data.model_data.instructions, data.model_data.input)
        if chars > max_input_chars:
            recorder.add_budget_exceeded(chars, max_input_chars)
            raise _Stop("budget_exceeded", "입력 예산(max_input_chars)을 넘어 보내지 않았다")
        return data.model_data

    run_config = RunConfig(tracing_disabled=True, call_model_input_filter=check_budget)

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

    # 장부: 입력의 근거 ID + 성공한 도구 호출의 agl_ + 모델에게 보인 레코드의 id(#211).
    # 오류·차단된 호출의 agl_과 결과 본문 속 ID 모양 문자열은 들어가지 않는다.
    ledger = set(task.allowed_evidence_ids) | tools.evidence_ids
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
    if isinstance(data, dict) and has_top_level_field(task.output_contract, "decided_at"):
        data["decided_at"] = time.time_ns() // 1_000_000  # 모델이 낸 시각은 쓰지 않는다
    try:
        validate_contract(task.output_contract, data)
    except ContractError as exc:
        return None, ", ".join(f"{v.path}: {v.rule}" for v in exc.violations)
    return data, None


def _redacted(row: dict[str, Any], redact: Any) -> dict[str, Any]:
    out = dict(row)
    for key in ("input", "output", "details"):
        out[key] = redact(row[key])
    return out


def _usage(rows: list[dict[str, Any]], started: float) -> dict[str, int]:
    # sent=false 줄(예산 초과, 시작 전 실패, 종료 줄)은 모델에 보낸 호출이 아니다
    models = [r for r in rows if r["kind"] == "model" and r["details"].get("sent") is not False]
    return {
        "turns": len(models),
        "tool_calls": sum(1 for r in rows if r["kind"] == "tool"),
        "tool_errors": sum(1 for r in rows if r["kind"] == "tool" and r["outcome"] == "error"),
        "tokens_in": sum(r["tokens_in"] or 0 for r in models),
        "tokens_out": sum(r["tokens_out"] or 0 for r in models),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _failed(failure: str, detail: str, run_id: str) -> AgentResult:
    return AgentResult(
        ok=False,
        output=None,
        failure=failure,
        detail=detail,
        run_id=run_id,  # type: ignore[arg-type]
    )
