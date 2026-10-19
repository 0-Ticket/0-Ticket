"""Embedding providers for box 8, selected through the ``embedders`` registry."""

from soc.config import Settings
from soc.plugins import PluginRegistry

from .base import Embedder, EmbedderFactory

EMBEDDERS = PluginRegistry("embedders")


def open_embedder(settings: Settings, registry: PluginRegistry | None = None) -> Embedder:
    """Open the configured embedding provider without naming its implementation."""
    registry = EMBEDDERS if registry is None else registry
    factory = registry.get(settings.embedder.provider)
    return factory(settings.embedder)


__all__ = ["EMBEDDERS", "Embedder", "EmbedderFactory", "open_embedder"]
