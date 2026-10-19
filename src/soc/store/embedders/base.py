"""Embedding provider boundary for box 8 (D-010)."""

from typing import Protocol

from soc.config import EmbedderSettings


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class EmbedderFactory(Protocol):
    def __call__(self, settings: EmbedderSettings) -> Embedder: ...
