"""Vector stores (unnumbered Vector DB), selected through the ``vector_stores`` registry."""

from soc.config import Settings
from soc.plugins import PluginRegistry

from .base import VectorSearchHit, VectorStore

VECTOR_STORES = PluginRegistry("vector_stores")


def open_vector_store(settings: Settings, registry: PluginRegistry | None = None) -> VectorStore:
    """Open the configured vector store without naming its implementation."""
    registry = VECTOR_STORES if registry is None else registry
    factory = registry.get(settings.vector_store.backend)
    return factory(settings)


__all__ = ["VECTOR_STORES", "VectorSearchHit", "VectorStore", "open_vector_store"]
