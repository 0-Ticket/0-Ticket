"""Provider-neutral request and response types for LLM implementations."""

from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    base_url: str
    model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    api_key: str | None = field(default=None, repr=False)
    # Providers must give up after this many seconds (llm.timeout_seconds).
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    tokens: int | None = None


class ProviderError(RuntimeError):
    """A provider failure represented by a safe, non-sensitive code.

    `retry_after_seconds` is only meaningful for `provider_rate_limited`: the wait the
    server asked for, or None when it gave no usable value.
    """

    SAFE_CODES = frozenset(
        {
            "provider_unavailable",
            "provider_timeout",
            "provider_rate_limited",
            "provider_invalid_response",
            "provider_error",
        }
    )

    def __init__(self, code: str, *, retry_after_seconds: float | None = None):
        self.code = code if code in self.SAFE_CODES else "provider_error"
        self.retry_after_seconds = (
            retry_after_seconds if self.code == "provider_rate_limited" else None
        )
        super().__init__(self.code)


class LLMProvider(Protocol):
    """One configured provider implementation."""

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...
