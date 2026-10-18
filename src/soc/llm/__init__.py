"""Shared LLM call path with prompt framing, output validation, retry, and logging."""

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from soc.config import LLMSettings, load_config
from soc.contracts import AgentStep, ContractValidationError, validate_contract
from soc.llm.base import ProviderError, ProviderRequest, ProviderResponse
from soc.llm.prompts import format_untrusted_data, load_prompt
from soc.llm.registry import create_provider_registry, get_provider_registry, instantiate_provider
from soc.plugins import PluginRegistry

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|token|api[_-]?key|secret|authorization|"
    r"access[_-]?key|client[_-]?secret)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\r\n,;}]+)"
)
_EXCERPT_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class CallContext:
    subject_type: Literal["ticket", "incident", "hunt"]
    subject_id: str
    step: int
    agent: str


@dataclass(frozen=True, slots=True)
class CallFailure:
    path: str
    rule: str


@dataclass(frozen=True, slots=True)
class LLMCallResult:
    value: BaseModel | None
    failure: CallFailure | None

    @property
    def ok(self) -> bool:
        return self.value is not None and self.failure is None


def _excerpt(value: str, api_key: str | None) -> str:
    redacted = value
    if api_key:
        redacted = redacted.replace(api_key, "[REDACTED]")
    redacted = _SECRET_ASSIGNMENT.sub(r'\1"[REDACTED]"', redacted)
    return redacted[:_EXCERPT_LIMIT]


def _parse_and_validate(
    contract_name: str, content: str
) -> tuple[BaseModel | None, CallFailure | None]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None, CallFailure(path="/", rule="invalid_json")
    try:
        return validate_contract(contract_name, parsed), None
    except ContractValidationError as error:
        return None, CallFailure(path=error.path, rule=error.rule)


def _make_agent_step(
    context: CallContext,
    prompt_version: str,
    model: str,
    input_text: str,
    output_text: str,
    tokens: int | None,
    latency_ms: int,
    api_key: str | None,
) -> AgentStep:
    return validate_contract(
        "AgentStep",
        {
            "subject_type": context.subject_type,
            "subject_id": context.subject_id,
            "step": context.step,
            "agent": context.agent,
            "action": "llm_call",
            "tool": None,
            "prompt_version": prompt_version,
            "input_excerpt": _excerpt(input_text, api_key),
            "output_excerpt": _excerpt(output_text, api_key),
            "model": model,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "created_at": time.time_ns() // 1_000_000,
        },
    )


def call_llm(
    *,
    prompt_path: str | Path,
    data: object,
    contract_name: str,
    context: CallContext,
    record_step: Callable[[AgentStep], None],
    settings: LLMSettings | None = None,
    provider_registry: PluginRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> LLMCallResult:
    """Call a configured provider, validate JSON, retry one validation failure, and log C8.

    The callback receives one C8 record for the logical call. Persistence is owned
    by the Agent Log box; this function only constructs and sends the contract.
    """
    settings = settings or load_config().llm
    environ = os.environ if environ is None else environ
    registry = provider_registry or get_provider_registry()
    prompt = load_prompt(prompt_path)
    untrusted_data = format_untrusted_data(data)
    input_text = f"{prompt.text}\n\n{untrusted_data}"
    model = settings.agents.get(context.agent)
    selected_model = model.model if model is not None else settings.model
    api_key = environ.get(settings.api_key_env) or None
    start = time.perf_counter()
    last_output = ""
    token_values: list[int] = []
    value: BaseModel | None = None
    failure: CallFailure | None = None

    try:
        provider = instantiate_provider(settings.provider, registry)
    except Exception:
        failure = CallFailure(path="/", rule="provider_unavailable")
    else:
        retry_feedback = ""
        for _ in range(2):
            request = ProviderRequest(
                base_url=settings.base_url,
                model=selected_model,
                system_prompt=prompt.text,
                user_prompt=f"{untrusted_data}{retry_feedback}",
                temperature=settings.temperature,
                api_key=api_key,
            )
            try:
                response = provider.complete(request)
            except ProviderError as error:
                failure = CallFailure(path="/", rule=error.code)
                break
            except Exception:
                failure = CallFailure(path="/", rule="provider_error")
                break
            if not isinstance(response, ProviderResponse) or not isinstance(response.content, str):
                failure = CallFailure(path="/", rule="provider_invalid_response")
                break
            last_output = response.content
            if isinstance(response.tokens, int) and not isinstance(response.tokens, bool):
                if response.tokens >= 0:
                    token_values.append(response.tokens)
            value, failure = _parse_and_validate(contract_name, response.content)
            if failure is None:
                break
            retry_feedback = (
                "\n\nThe previous response did not satisfy the required JSON contract. "
                "Return corrected JSON only. "
                f"path: {failure.path}; rule: {failure.rule}."
            )

    elapsed_ms = max(0, int((time.perf_counter() - start) * 1000))
    tokens = sum(token_values) if token_values else None
    record = _make_agent_step(
        context=context,
        prompt_version=prompt.version,
        model=selected_model,
        input_text=input_text,
        output_text=last_output,
        tokens=tokens,
        latency_ms=elapsed_ms,
        api_key=api_key,
    )
    record_step(record)
    return LLMCallResult(value=value, failure=failure)


__all__ = [
    "CallContext",
    "CallFailure",
    "LLMCallResult",
    "call_llm",
    "create_provider_registry",
    "format_untrusted_data",
    "load_prompt",
]
