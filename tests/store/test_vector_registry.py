from importlib.metadata import entry_points
from types import SimpleNamespace

from soc.config import load_config
from soc.plugins import PluginRegistry
from soc.store.embedders import open_embedder
from soc.store.embedders.ollama import create_ollama_embedder
from soc.store.vectors import open_vector_store
from soc.store.vectors.qdrant import create_qdrant_vector_store
from soc.store.vectors.tickets import VectorTicketService


def test_vector_store_and_embedder_defaults_are_registered_as_plugins():
    vector_entry_points = {
        entry.name: entry.value for entry in entry_points(group="zero_ticket_soc.vector_stores")
    }
    embedder_entry_points = {
        entry.name: entry.value for entry in entry_points(group="zero_ticket_soc.embedders")
    }

    assert vector_entry_points["qdrant"] == "soc.store.vectors.qdrant:create_qdrant_vector_store"
    assert embedder_entry_points["ollama"] == "soc.store.embedders.ollama:create_ollama_embedder"
    assert PluginRegistry("vector_stores").get("qdrant") is create_qdrant_vector_store
    assert PluginRegistry("embedders").get("ollama") is create_ollama_embedder


def test_fake_vector_store_replaces_the_configured_default():
    calls = []
    fake_store = object()

    def fake_factory(settings):
        calls.append(settings)
        return fake_store

    settings = load_config(environ={})
    registry = PluginRegistry("vector_stores")
    registry.register("fake", fake_factory)
    settings = settings.model_copy(
        update={"vector_store": settings.vector_store.model_copy(update={"backend": "fake"})}
    )

    assert open_vector_store(settings, registry=registry) is fake_store
    assert calls == [settings]


def test_fake_embedder_replaces_the_configured_default():
    fake_embedder = object()
    settings = SimpleNamespace(embedder=SimpleNamespace(provider="fake"))
    registry = PluginRegistry("embedders")
    registry.register("fake", lambda configured: fake_embedder)

    assert open_embedder(settings, registry=registry) is fake_embedder


def test_registered_fake_store_and_embedder_replace_configured_defaults_in_service():
    store_closed = []
    fake_store = SimpleNamespace(close=lambda: store_closed.append(True))
    fake_embedder = object()
    settings = load_config(environ={})
    settings = settings.model_copy(
        update={
            "vector_store": settings.vector_store.model_copy(update={"backend": "fake_store"}),
            "embedder": settings.embedder.model_copy(update={"provider": "fake_embedder"}),
        }
    )
    vector_registry = PluginRegistry("vector_stores")
    embedder_registry = PluginRegistry("embedders")
    vector_registry.register("fake_store", lambda configured: fake_store)
    embedder_registry.register("fake_embedder", lambda configured: fake_embedder)

    service = VectorTicketService.from_settings(
        settings,
        vector_registry=vector_registry,
        embedder_registry=embedder_registry,
    )

    assert isinstance(service, VectorTicketService)
    service.close()
    assert store_closed == [True]
