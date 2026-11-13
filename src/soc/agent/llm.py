"""LLM 연결, 429 재시도 래퍼, 입력 글자 수(#210).

연결은 OpenAIChatCompletionsModel + AsyncOpenAI(base_url=...) 하나다(기본 LLM, D-009). 제공자는
[llm]의 base_url·model·api_key_env 값으로만 바뀌고, 제공자별 분기는 두지 않는다.
재시도는 RetryingModel 하나만 한다.
openai 자체 재시도(max_retries=0)와 SDK의 ModelSettings.retry는 끈다.
"""

import json
import math
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

import httpx2
import openai
from agents import OpenAIChatCompletionsModel
from agents.models.interface import Model

from soc.agent.agent_log import jsonable

# 키가 필요 없는 제공자(Ollama 등, api_key_env = "")에 보내는 고정 값. 비밀이 아니다.
PLACEHOLDER_API_KEY = "no-key"
MAX_WAIT_SECONDS = 60.0

Sleep = Callable[[float], Awaitable[None]]


class LLMConfigError(Exception):
    """연결 설정이 없거나 키 환경변수가 없다. 메시지에 주소·키를 넣지 않는다."""


def build_client(
    config: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> tuple[openai.AsyncOpenAI, str]:
    """설정의 [llm]으로 openai 클라이언트를 만든다. (클라이언트, 모델 이름)을 돌려준다.

    run_agent는 run마다 이것을 만들고 끝날 때 닫는다(#280). http_client는 테스트가 가짜 전송
    계층을 넣는 자리다. 만들 때 네트워크에 접속하지 않는다.
    """
    environ = os.environ if environ is None else environ
    llm = config["llm"]
    base_url = str(llm.get("base_url", ""))
    model_name = str(llm.get("model", ""))
    if not base_url or not model_name:
        raise LLMConfigError("LLM 연결 설정이 없다")
    key_env = str(llm.get("api_key_env", ""))
    if key_env:
        api_key = environ.get(key_env)
        if not api_key:
            raise LLMConfigError(f"LLM 키 환경변수({key_env})가 비어 있다")
    else:
        api_key = PLACEHOLDER_API_KEY
    client = openai.AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=float(llm["timeout_seconds"]),
        max_retries=0,
        http_client=http_client,
    )
    return client, model_name


def build_model(
    config: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> tuple[Model, str]:
    """설정의 [llm]으로 운영 모델을 만든다. (모델, Agent Log에 쓸 모델 이름)을 돌려준다."""
    client, model_name = build_client(config, environ, http_client)
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client), model_name


class RetryingModel(Model):
    """어떤 Model이든 감싸 429(RateLimitError)만 다시 부른다. 그 밖의 오류는 그대로 올린다.

    SDK 훅(on_llm_start·on_llm_end)은 이 래퍼 바깥에서 한 번씩 불리므로
    Agent Log는 한 호출에 한 줄이다.
    """

    def __init__(
        self, inner: Model, *, retries: int, sleep: Sleep, on_retry: Callable[[], None]
    ) -> None:
        self._inner = inner
        self._retries = retries
        self._sleep = sleep
        self._on_retry = on_retry

    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                return await self._inner.get_response(*args, **kwargs)
            except openai.RateLimitError as exc:
                if attempt >= self._retries:
                    raise
                self._on_retry()
                await self._sleep(retry_delay(exc, attempt))
                attempt += 1

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError("스트리밍은 쓰지 않는다")


def retry_delay(exc: openai.RateLimitError, attempt: int) -> float:
    """Retry-After(초)가 있으면 그만큼, 없거나 읽지 못하면 1·2·4초…. 어느 쪽이든 60초까지."""
    delay = _retry_after_seconds(exc)
    if delay is None:
        delay = float(2**attempt)
    return min(delay, MAX_WAIT_SECONDS)


def _retry_after_seconds(exc: openai.RateLimitError) -> float | None:
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def input_chars(instructions: str | None, items: Any) -> int:
    """그 호출에 보내는 system 지시 글자 수 + 입력 항목을 JSON으로 바꾼 글자 수."""
    payload = json.dumps(jsonable(items), ensure_ascii=False)
    return len(instructions or "") + len(payload)
