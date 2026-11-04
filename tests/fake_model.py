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
            raise _error(step["raise"])
        if "tool_call" in step:
            call = step["tool_call"]
            item = function_call(call["name"], call["arguments"], call_id=f"call_{n}")
        elif "final" in step:
            item = assistant_message(json.dumps(step["final"], ensure_ascii=False))
        else:
            item = assistant_message(step["final_text"])
        usage = step.get("usage", {})
        tokens_in = usage.get("input_tokens", 10)
        tokens_out = usage.get("output_tokens", 5)
        return ModelResponse(
            output=[item],
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


def _error(kind: str) -> Exception:
    if kind == "rate_limited":
        return openai.RateLimitError(
            "rate limited", response=httpx2.Response(429, request=_REQUEST), body=None
        )
    if kind == "provider_error":
        return openai.APIConnectionError(request=_REQUEST)
    raise ValueError(f"알 수 없는 raise 값: {kind}")
