"""OpenAI Chat Completions-compatible LLM provider."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from soc.llm.base import ProviderError, ProviderRequest, ProviderResponse


class OpenAICompatibleProvider:
    """Call a configured OpenAI-compatible Chat Completions endpoint."""

    timeout_seconds = 60

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        endpoint = f"{request.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if request.api_key:
            headers["Authorization"] = f"Bearer {request.api_key}"
        http_request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError):
            raise ProviderError("provider_unavailable") from None
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ProviderError("provider_invalid_response") from None

        try:
            content = decoded["choices"][0]["message"]["content"]
            usage = decoded.get("usage", {})
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        except (AttributeError, IndexError, KeyError, TypeError):
            raise ProviderError("provider_invalid_response") from None
        if not isinstance(content, str):
            raise ProviderError("provider_invalid_response")
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            tokens = None
        return ProviderResponse(content=content, tokens=tokens)
