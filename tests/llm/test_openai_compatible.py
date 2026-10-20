"""OpenAI-compatible HTTP request tests use a local fake transport."""

import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from soc.llm.base import ProviderError, ProviderRequest
from soc.llm.providers.openai_compatible import OpenAICompatibleProvider


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _request(api_key=None, **updates):
    return ProviderRequest(
        base_url="http://localhost:11434/v1",
        api_key=api_key,
        model="granite4:micro",
        system_prompt="Return JSON only.",
        user_prompt="<untrusted_data>{}</untrusted_data>",
        temperature=0,
        **updates,
    )


def _http_error(code, headers=None):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return HTTPError(
        "http://localhost:11434/v1/chat/completions",
        code,
        "synthetic reason",
        message,
        io.BytesIO(b"secret response body"),
    )


def _raise(error):
    def fail(*_, **__):
        raise error

    return fail


def test_provider_sends_openai_chat_completion_and_extracts_usage(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            {
                "choices": [{"message": {"content": '{"verdict":"unknown"}'}}],
                "usage": {"total_tokens": 17},
            }
        )

    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", fake_urlopen)
    response = OpenAICompatibleProvider().complete(_request("test-api-secret"))

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-api-secret"
    assert captured["body"]["model"] == "granite4:micro"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0]["role"] == "system"
    assert captured["timeout"] > 0
    assert "test-api-secret" not in repr(_request("test-api-secret"))
    assert response.content == '{"verdict":"unknown"}'
    assert response.tokens == 17


def test_provider_omits_auth_header_when_local_model_has_no_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return FakeHTTPResponse({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", fake_urlopen)
    OpenAICompatibleProvider().complete(_request())

    assert "Authorization" not in captured["headers"]


def test_provider_failure_does_not_echo_transport_details(monkeypatch):
    def fail(*_, **__):
        raise OSError("secret transport detail")

    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", fail)
    with pytest.raises(ProviderError, match="provider_unavailable") as caught:
        OpenAICompatibleProvider().complete(_request())
    assert "secret transport detail" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_provider_uses_the_request_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        return FakeHTTPResponse({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", fake_urlopen)
    OpenAICompatibleProvider().complete(_request(timeout_seconds=123))

    assert captured["timeout"] == 123
    assert not hasattr(OpenAICompatibleProvider, "timeout_seconds")


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        URLError(TimeoutError("timed out")),
    ],
)
def test_timeout_is_reported_as_provider_timeout(monkeypatch, error):
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request())
    assert caught.value.code == "provider_timeout"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "provider_auth_failed"),
        (403, "provider_auth_failed"),
        (404, "provider_model_not_found"),
        (413, "provider_request_too_large"),
    ],
)
def test_http_status_has_its_own_failure_code(monkeypatch, status, code):
    error = _http_error(status)
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request("test-api-secret"))
    assert caught.value.code == code
    assert caught.value.__cause__ is None
    assert "secret response body" not in str(caught.value)
    assert "test-api-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [URLError(ConnectionRefusedError("refused")), ConnectionResetError("reset"), 400, 500, 503],
)
def test_other_connection_failures_stay_provider_unavailable(monkeypatch, error):
    error = _http_error(error) if isinstance(error, int) else error
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request())
    assert caught.value.code == "provider_unavailable"


@pytest.mark.parametrize(
    ("headers", "retry_after"),
    [({"Retry-After": "7"}, 7.0), ({"Retry-After": "1.5"}, 1.5), ({}, None)],
)
def test_429_is_rate_limited_with_retry_after(monkeypatch, headers, retry_after):
    error = _http_error(429, headers)
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request())
    assert caught.value.code == "provider_rate_limited"
    assert caught.value.retry_after_seconds == retry_after
    assert "secret response body" not in str(caught.value)
    assert "synthetic reason" not in str(caught.value)


@pytest.mark.parametrize("value", ["soon", "-3", "nan", "inf"])
def test_unusable_retry_after_is_ignored(monkeypatch, value):
    error = _http_error(429, {"Retry-After": value})
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request())
    assert caught.value.retry_after_seconds is None


def test_retry_after_http_date_becomes_seconds(monkeypatch):
    error = _http_error(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    monkeypatch.setattr("soc.llm.providers.openai_compatible.urlopen", _raise(error))
    monkeypatch.setattr("soc.llm.providers.openai_compatible.time.time", lambda: 1792567670.0)
    with pytest.raises(ProviderError) as caught:
        OpenAICompatibleProvider().complete(_request())
    assert caught.value.retry_after_seconds == 10.0


def test_unknown_error_codes_stay_safe():
    error = ProviderError("raw upstream text")
    assert error.code == "provider_error"
    assert error.retry_after_seconds is None
