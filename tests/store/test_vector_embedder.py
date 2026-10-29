import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from soc.config import load_config
from soc.plugins import PluginRegistry
from soc.store.embedders import open_embedder
from soc.store.embedders.ollama import EmbeddingError, OllamaEmbedder


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_ollama_embedder_posts_model_and_text_to_native_embed_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse(b'{"embeddings": [[0.1, 0.2, 0.3]]}')

    monkeypatch.setattr("soc.store.embedders.ollama.urlopen", fake_urlopen)
    embedder = OllamaEmbedder(
        base_url="http://localhost:11434/",
        model="bge-m3",
        dimensions=3,
        timeout_seconds=7,
    )

    assert embedder.embed("synthetic ticket text") == [0.1, 0.2, 0.3]
    assert captured == {
        "url": "http://localhost:11434/api/embed",
        "payload": {"model": "bge-m3", "input": "synthetic ticket text"},
        "timeout": 7,
    }


def test_ollama_embedder_rejects_a_wrong_vector_dimension(monkeypatch):
    monkeypatch.setattr(
        "soc.store.embedders.ollama.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"embeddings": [[0.1, 0.2]]}'),
    )
    embedder = OllamaEmbedder("http://localhost:11434", "bge-m3", 3)

    with pytest.raises(EmbeddingError, match="dimension_mismatch"):
        embedder.embed("text")


def test_ollama_embedder_does_not_expose_provider_response_on_failure(monkeypatch):
    monkeypatch.setattr(
        "soc.store.embedders.ollama.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("private endpoint detail")),
    )
    embedder = OllamaEmbedder("http://localhost:11434", "bge-m3", 3)

    with pytest.raises(EmbeddingError) as caught:
        embedder.embed("text")

    assert str(caught.value) == "embedder_unavailable"
    assert "private endpoint detail" not in str(caught.value)


def test_ollama_embedder_reports_http_status_without_exposing_response(monkeypatch):
    response_body = BytesIO(b"private server response")
    error = HTTPError(
        "http://localhost:11434/api/embed",
        404,
        "private server detail",
        {},
        response_body,
    )

    def raise_http_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("soc.store.embedders.ollama.urlopen", raise_http_error)
    embedder = OllamaEmbedder("http://localhost:11434", "bge-m3", 3)

    with pytest.raises(EmbeddingError) as caught:
        embedder.embed("text")

    assert str(caught.value) == "embedder_http_404"
    assert "private" not in str(caught.value)
    assert response_body.closed


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private timeout detail"),
        URLError(TimeoutError("private timeout detail")),
    ],
)
def test_ollama_embedder_reports_timeout_without_exposing_details(monkeypatch, error):
    def raise_timeout(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("soc.store.embedders.ollama.urlopen", raise_timeout)
    embedder = OllamaEmbedder("http://localhost:11434", "bge-m3", 3)

    with pytest.raises(EmbeddingError) as caught:
        embedder.embed("text")

    assert str(caught.value) == "embedder_timeout"
    assert "private timeout detail" not in str(caught.value)


def test_fake_embedder_replaces_configured_default():
    calls = []

    class FakeEmbedder:
        def embed(self, text):
            calls.append(text)
            return [0.0] * 1024

    def fake_factory(settings):
        assert settings.model == "bge-m3"
        return FakeEmbedder()

    settings = load_config(environ={})
    registry = PluginRegistry("embedders")
    registry.register("fake", fake_factory)
    settings = settings.model_copy(
        update={"embedder": settings.embedder.model_copy(update={"provider": "fake"})}
    )

    embedder = open_embedder(settings, registry=registry)

    assert embedder.embed("fake text") == [0.0] * 1024
    assert calls == ["fake text"]
