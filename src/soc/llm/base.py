"""Provider-neutral request and response types for LLM implementations."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    base_url: str
    model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    tokens: int | None = None


class ProviderError(RuntimeError):
    """A provider failure represented by a safe, non-sensitive code."""

    SAFE_CODES = frozenset({"provider_unavailable", "provider_invalid_response", "provider_error"})

    def __init__(self, code: str):
        self.code = code if code in self.SAFE_CODES else "provider_error"
        super().__init__(self.code)


class LLMProvider(Protocol):
    """One configured provider implementation."""

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...
