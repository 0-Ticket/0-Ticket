"""OpenAI Chat Completions-compatible LLM provider."""

import json
import math
import time
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from soc.llm.base import ProviderError, ProviderRequest, ProviderResponse

_TOO_MANY_REQUESTS = 429
# HTTP statuses worth telling apart in logs; any other status is provider_unavailable.
_STATUS_CODES = {
    401: "provider_auth_failed",
    403: "provider_auth_failed",
    404: "provider_model_not_found",
    413: "provider_request_too_large",
}


def _retry_after_seconds(value: str | None) -> float | None:
    """Seconds from a Retry-After header (delay or HTTP date); None if unusable."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        seconds = max(0.0, seconds)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    return isinstance(error, URLError) and isinstance(error.reason, TimeoutError)


class OpenAICompatibleProvider:
    """Call a configured OpenAI-compatible Chat Completions endpoint."""

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
            with urlopen(http_request, timeout=request.timeout_seconds) as response:
                decoded = json.loads(response.read())
        except HTTPError as error:
            # Only the status and Retry-After are read; the body may echo the request.
            code, headers = error.code, error.headers
            error.close()
            if code == _TOO_MANY_REQUESTS:
                retry_after = _retry_after_seconds(headers.get("Retry-After") if headers else None)
                raise ProviderError(
                    "provider_rate_limited", retry_after_seconds=retry_after
                ) from None
            raise ProviderError(_STATUS_CODES.get(code, "provider_unavailable")) from None
        except (URLError, TimeoutError, OSError) as error:
            code = "provider_timeout" if _is_timeout(error) else "provider_unavailable"
            raise ProviderError(code) from None
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
