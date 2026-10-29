"""Local Ollama embedding provider using its native ``/api/embed`` endpoint."""

import json
import math
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from soc.config import EmbedderSettings


class EmbeddingError(RuntimeError):
    """A safe embedding failure code that never includes provider response text."""


class OllamaEmbedder:
    """Create one dense embedding with a locally served Ollama model."""

    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("embedding_text_required")
        request = Request(
            f"{self._base_url}/api/embed",
            data=json.dumps(
                {"model": self._model, "input": text},
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError):
            raise EmbeddingError("embedder_unavailable") from None
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise EmbeddingError("embedder_invalid_response") from None

        try:
            embeddings = payload["embeddings"]
            vector = embeddings[0]
        except (KeyError, IndexError, TypeError):
            raise EmbeddingError("embedder_invalid_response") from None
        if not isinstance(payload, Mapping) or not isinstance(embeddings, list):
            raise EmbeddingError("embedder_invalid_response")
        if len(embeddings) != 1 or not isinstance(vector, list):
            raise EmbeddingError("embedder_invalid_response")
        if len(vector) != self._dimensions:
            raise EmbeddingError("embedding_dimension_mismatch")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingError("embedder_invalid_response")
        return [float(value) for value in vector]


def create_ollama_embedder(settings: EmbedderSettings) -> OllamaEmbedder:
    """Factory registered as ``ollama`` in the ``embedders`` entry point group."""
    return OllamaEmbedder(
        settings.base_url,
        settings.model,
        settings.dimensions,
        settings.timeout_seconds,
    )
