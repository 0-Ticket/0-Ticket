"""LLM 연결·429 재시도·입력 예산(#210). 모두 네트워크 없이 돈다."""

import json
from typing import Any

import httpx2
import pytest
from agents import OpenAIChatCompletionsModel
from fake_model import FakeModel
from test_agent_core import CONFIG, REGISTRY, make_task, no_sleep

from soc.agent import run_agent
from soc.agent.agent_log import MemoryLogSink
from soc.agent.llm import PLACEHOLDER_API_KEY, LLMConfigError, build_model, input_chars
from soc.agent.runner import run_task
from soc.contracts import validate_contract

FAKE_KEY = "fake-llm-key-5555"
FOUNDRY_URL = "https://fake-resource.openai.azure.com/openai/v1/"

PROVIDERS = {
    "foundry": {
        "base_url": FOUNDRY_URL,
        "model": "gpt-oss-120b-deploy",
        "api_key_env": "LLM_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "api_key_env": "LLM_API_KEY",
    },
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "gpt-oss:20b", "api_key_env": ""},
}


def llm_config(**llm: Any) -> dict[str, Any]:
    return {**CONFIG, "llm": {**CONFIG["llm"], **llm}}


def stage_config(**l1: Any) -> dict[str, Any]:
    return {**CONFIG, "agent": {**CONFIG["agent"], "l1": {**CONFIG["agent"]["l1"], **l1}}}


class SleepSpy:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def run(scenario: str, *, config: dict[str, Any] = CONFIG, sleep: Any = no_sleep):
    model = FakeModel(scenario)
    sink = MemoryLogSink()
    result = run_task(
        make_task(),
        model=model,
        model_name="fake-model",
        log_sink=sink,
        config=config,
        registry=REGISTRY,
        sleep=sleep,
    )
    return result, model, sink


# 연결: 설정의 base_url·model·키 처리를 그대로 쓴다


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_client_uses_config_values(provider: str) -> None:
    llm = PROVIDERS[provider]
    model, name = build_model(llm_config(**llm), environ={"LLM_API_KEY": FAKE_KEY})
    assert isinstance(model, OpenAIChatCompletionsModel)
    assert name == llm["model"]
    assert model.model == llm["model"]
    client = model._client
    assert str(client.base_url).rstrip("/") == llm["base_url"].rstrip("/")
    assert client.max_retries == 0  # 재시도는 우리 래퍼 하나만 한다
    assert client.timeout == 60
    expected_key = FAKE_KEY if llm["api_key_env"] else PLACEHOLDER_API_KEY
    assert client.api_key == expected_key


def test_timeout_comes_from_config() -> None:
    model, _ = build_model(
        llm_config(**PROVIDERS["groq"], timeout_seconds=15), environ={"LLM_API_KEY": FAKE_KEY}
    )
    assert model._client.timeout == 15


@pytest.mark.parametrize(
    "llm",
    [
        {"base_url": "", "model": "gpt-oss-120b"},
        {"base_url": FOUNDRY_URL, "model": ""},
    ],
)
def test_empty_connection_settings_are_rejected(llm: dict[str, str]) -> None:
    with pytest.raises(LLMConfigError):
        build_model(llm_config(**llm), environ={"LLM_API_KEY": FAKE_KEY})


def test_missing_key_env_is_rejected_without_secrets() -> None:
    with pytest.raises(LLMConfigError) as info:
        build_model(llm_config(**PROVIDERS["foundry"]), environ={})
    assert FOUNDRY_URL not in str(info.value)
    assert "fake-resource" not in str(info.value)


def test_run_agent_missing_key_is_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # run_agent는 DATABASE_URL을 먼저 읽는다(#278). 기록기는 메모리로 바꾼다
    monkeypatch.setenv("DATABASE_URL", "postgresql://soc@127.0.0.1:1/soc")
    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", lambda *a, **k: MemoryLogSink())
    monkeypatch.setattr("soc.agent.runner.load_config", lambda: llm_config(**PROVIDERS["foundry"]))
    result = run_agent(make_task())
    assert result.ok is False
    assert result.failure == "provider_error"
    assert "fake-resource" not in (result.detail or "")


def test_reasoning_effort_per_stage() -> None:
    _, model, _ = run("verdict_ok")
    assert model.calls[0]["model_settings"].reasoning.effort == "low"
    _, model, _ = run("verdict_ok", config=stage_config(reasoning_effort="medium"))
    assert model.calls[0]["model_settings"].reasoning.effort == "medium"


def test_sdk_retry_is_not_enabled() -> None:
    _, model, _ = run("verdict_ok")
    assert model.calls[0]["model_settings"].retry is None


def test_request_goes_to_base_url_with_model_effort_and_key() -> None:
    """실제 openai 클라이언트가 만든 요청을 가짜 전송 계층에서 받아 본다(네트워크 없음)."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_completion('{"decision": "undetermined"}'))

    model, _ = build_model(
        llm_config(**PROVIDERS["foundry"]),
        environ={"LLM_API_KEY": FAKE_KEY},
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    result = run_task(
        make_task(),
        model=model,
        model_name="gpt-oss-120b-deploy",
        log_sink=MemoryLogSink(),
        config=llm_config(**PROVIDERS["foundry"]),
        registry=REGISTRY,
        sleep=no_sleep,
    )
    assert result.failure == "format_error"  # 답 모양은 관심 밖이다. 요청만 본다
    request = seen[0]
    assert str(request.url) == FOUNDRY_URL + "chat/completions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "gpt-oss-120b-deploy"
    assert body["reasoning_effort"] == "low"


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-oss-120b-deploy",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# 429 재시도


def test_rate_limited_then_ok_retries_with_backoff() -> None:
    sleep = SleepSpy()
    result, model, sink = run("rate_limited_then_ok", sleep=sleep)
    assert result.ok is True
    assert len(model.calls) == 4
    assert sleep.waits == [1, 2, 4]
    models = [r for r in sink.rows if r["kind"] == "model"]
    assert len(models) == 1  # 한 호출에 한 줄
    assert models[0]["details"]["retries"] == 3
    assert models[0]["outcome"] == "ok"


def test_rate_limited_after_configured_retries() -> None:
    sleep = SleepSpy()
    result, model, sink = run("rate_limited", sleep=sleep)
    assert result.failure == "rate_limited"
    assert len(model.calls) == 4  # 처음 1회 + 재시도 3회
    assert len(sleep.waits) == 3
    last = sink.rows[-1]
    assert last["kind"] == "model"
    assert last["outcome"] == "error"
    assert last["details"]["retries"] == 3
    assert last["details"]["failure"] == "rate_limited"
    validate_contract("agent_log", last)


def test_retry_count_comes_from_config() -> None:
    sleep = SleepSpy()
    result, model, _ = run("rate_limited", config=llm_config(rate_limit_retries=1), sleep=sleep)
    assert result.failure == "rate_limited"
    assert len(model.calls) == 2
    assert sleep.waits == [1]


def test_retry_after_is_used_and_capped() -> None:
    sleep = SleepSpy()
    result, _, _ = run("rate_limited_retry_after", sleep=sleep)
    assert result.ok is True
    assert sleep.waits == [2.5, 60, 4]  # 2.5초, 120초는 60초로, 읽을 수 없으면 1·2·4초 차례


def test_ok_run_has_zero_retries() -> None:
    _, _, sink = run("verdict_ok")
    for row in sink.rows:
        if row["kind"] == "model":
            assert row["details"]["retries"] == 0


@pytest.mark.parametrize("scenario", ["timeout", "auth_error", "provider_error"])
def test_non_429_errors_are_provider_error_without_retry(scenario: str) -> None:
    sleep = SleepSpy()
    result, _, _ = run(scenario, sleep=sleep)
    assert result.failure == "provider_error"
    assert sleep.waits == []


@pytest.mark.parametrize("scenario", ["timeout", "auth_error", "provider_error", "rate_limited"])
def test_failure_detail_has_no_key_or_address(
    scenario: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
    result, _, _ = run(scenario, config=llm_config(**PROVIDERS["foundry"]))
    detail = result.detail or ""
    assert result.failure in ("provider_error", "rate_limited")
    for secret in (FAKE_KEY, "llm.example.com", FOUNDRY_URL, "fake-resource", "invalid api key"):
        assert secret not in detail


def test_real_client_429_is_retried_then_rate_limited() -> None:
    """openai 클라이언트가 받은 실제 429 응답(Retry-After 포함)을 래퍼가 다시 부른다."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(429, headers={"retry-after": "3"}, json={"error": {}})

    config = llm_config(**PROVIDERS["foundry"], rate_limit_retries=2)
    model, _ = build_model(
        config,
        environ={"LLM_API_KEY": FAKE_KEY},
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    sleep = SleepSpy()
    result = run_task(
        make_task(),
        model=model,
        model_name="gpt-oss-120b-deploy",
        log_sink=MemoryLogSink(),
        config=config,
        registry=REGISTRY,
        sleep=sleep,
    )
    assert result.failure == "rate_limited"
    assert len(calls) == 3  # openai 자체 재시도는 꺼져 있다
    assert sleep.waits == [3, 3]
    assert FOUNDRY_URL not in (result.detail or "")


# 입력 예산


def _sizes() -> list[int]:
    """예산이 넉넉할 때 호출마다 보낸 글자 수."""
    _, model, _ = run("verdict_ok")
    return [input_chars(c["system"], c["input"]) for c in model.calls]


def test_input_chars_counts_instructions_and_json_without_ascii_escape() -> None:
    items = [{"role": "user", "content": "한글"}]
    expected = len("지시") + len(json.dumps(items, ensure_ascii=False))
    assert input_chars("지시", items) == expected
    assert input_chars(None, []) == len("[]")


def test_first_call_over_budget_is_not_sent() -> None:
    first = _sizes()[0]
    result, model, sink = run("verdict_ok", config=stage_config(max_input_chars=first - 1))
    assert result.ok is False
    assert result.failure == "budget_exceeded"
    assert model.calls == []  # 보내지 않았다
    assert len(sink.rows) == 1
    row = sink.rows[0]
    validate_contract("agent_log", row)
    assert row["kind"] == "model"
    assert row["outcome"] == "error"
    assert row["details"]["failure"] == "budget_exceeded"
    assert row["input"] == {"chars": first, "max_input_chars": first - 1}
    assert row["output"] is None
    assert row["tokens_in"] is None and row["tokens_out"] is None


def test_input_at_budget_is_sent() -> None:
    sizes = _sizes()
    result, _, _ = run("verdict_ok", config=stage_config(max_input_chars=max(sizes)))
    assert result.ok is True


def test_middle_call_over_budget_keeps_earlier_rows_ok() -> None:
    first, second = _sizes()
    assert second > first
    result, model, sink = run("verdict_ok", config=stage_config(max_input_chars=first))
    assert result.failure == "budget_exceeded"
    assert len(model.calls) == 1
    assert [r["kind"] for r in sink.rows] == ["model", "tool", "model"]
    sent, tool, budget = sink.rows
    for row in sink.rows:
        validate_contract("agent_log", row)
    assert sent["outcome"] == "ok"
    assert "failure" not in sent["details"]
    assert tool["outcome"] == "ok"
    assert budget["outcome"] == "error"
    assert budget["details"]["failure"] == "budget_exceeded"
    assert budget["input"] == {"chars": second, "max_input_chars": first}
    assert budget["output"] is None
    assert budget["tokens_in"] is None and budget["tokens_out"] is None
    assert [r["seq"] for r in sink.rows] == [1, 2, 3]
