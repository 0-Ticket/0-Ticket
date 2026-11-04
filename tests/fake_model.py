"""테스트용 가짜 모델. tests/fixtures/agent/<이름>.json 시나리오대로 답한다.

시나리오 파일 형식은 docs/notes/209-agent-core.md "다음 사람이 알아야 할 것"에 있다.
실제 모델 대신 쓰므로 tests/ 안에서만 쓴다.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import openai
from agents import ModelResponse, ModelSettings, Usage
from agents.models.interface import Model, ModelTracing
from agents.testing import assistant_message, function_call

SCENARIOS = Path(__file__).parent / "fixtures" / "agent"
_REQUEST = httpx2.Request("POST", "https://llm.example.com/v1/chat/completions")


def load_scenario(name: str) -> dict[str, Any]:
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


class FakeModel(Model):
    """steps를 앞에서부터 하나씩 내놓는다. 호출마다 받은 입력을 calls에 남긴다."""

    def __init__(self, scenario: str | dict[str, Any]) -> None:
        data = load_scenario(scenario) if isinstance(scenario, str) else scenario
        self.steps: list[dict[str, Any]] = list(data["steps"])
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        self.calls.append(
            {
                "system": system_instructions,
                "input": input,
                "model_settings": model_settings,
                "tools": [t.name for t in tools],
                "output_schema": output_schema,
            }
        )
        if not self.steps:
            raise AssertionError("시나리오의 steps를 다 썼는데 모델이 또 불렸다")
        step = self.steps.pop(0)
        n = len(self.calls)
        if "raise" in step:
            raise _error(step["raise"], step.get("retry_after"))
        if "tool_call" in step:
            call = step["tool_call"]
            items = [function_call(call["name"], call["arguments"], call_id=f"call_{n}")]
        elif "tool_calls" in step:
            # 한 응답에 도구 호출 여러 개(#211). call_id는 call_<호출 번호>_<순서>
            items = [
                function_call(c["name"], c["arguments"], call_id=f"call_{n}_{i}")
                for i, c in enumerate(step["tool_calls"])
            ]
        elif "final" in step:
            items = [assistant_message(json.dumps(step["final"], ensure_ascii=False))]
        elif "final_fn" in step:
            # 테스트 코드 안에서만 쓰는 함수 step(#211). 지금까지의 도구 결과 문자열 목록을 받아
            # 최종 JSON 값을 만든다. 실행 중에 정해지는 call_id(agl_)를 인용할 때 쓴다.
            value = step["final_fn"](tool_outputs(input))
            items = [assistant_message(json.dumps(value, ensure_ascii=False))]
        else:
            items = [assistant_message(step["final_text"])]
        usage = step.get("usage", {})
        tokens_in = usage.get("input_tokens", 10)
        tokens_out = usage.get("output_tokens", 5)
        return ModelResponse(
            output=items,
            usage=Usage(
                requests=1,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                total_tokens=tokens_in + tokens_out,
            ),
            response_id=None,
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError("가짜 모델은 스트리밍을 쓰지 않는다")


def tool_outputs(items: Any) -> list[str]:
    """모델 입력 항목에서 도구 결과(function_call_output) 문자열을 순서대로 꺼낸다."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            out.append(str(item.get("output")))
    return out


def _error(kind: str, retry_after: str | None = None) -> Exception:
    if kind == "rate_limited":
        headers = {} if retry_after is None else {"retry-after": retry_after}
        response = httpx2.Response(429, headers=headers, request=_REQUEST)
        return openai.RateLimitError("rate limited", response=response, body=None)
    if kind == "provider_error":
        return openai.APIConnectionError(request=_REQUEST)
    if kind == "timeout":
        return openai.APITimeoutError(request=_REQUEST)
    if kind == "auth":
        response = httpx2.Response(401, request=_REQUEST)
        return openai.AuthenticationError("invalid api key", response=response, body=None)
    raise ValueError(f"알 수 없는 raise 값: {kind}")
