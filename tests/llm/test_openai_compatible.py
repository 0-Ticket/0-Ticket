"""OpenAI-compatible HTTP request tests use a local fake transport."""

import json

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


def _request(api_key=None):
    return ProviderRequest(
        base_url="http://localhost:11434/v1",
        api_key=api_key,
        model="granite4:micro",
        system_prompt="Return JSON only.",
        user_prompt="<untrusted_data>{}</untrusted_data>",
        temperature=0,
    )


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
