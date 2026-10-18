"""Name-based registry for built-in and externally installed LLM providers."""

from soc.llm.providers import OpenAICompatibleProvider
from soc.plugins import PluginRegistry


def create_provider_registry() -> PluginRegistry:
    """Create the LLM provider registry with the built-in OpenAI-compatible provider."""
    registry = PluginRegistry("llm_providers")
    registry.register("openai_compatible", OpenAICompatibleProvider)
    return registry


_PROVIDER_REGISTRY = create_provider_registry()


def get_provider_registry() -> PluginRegistry:
    """Return the process-wide provider registry."""
    return _PROVIDER_REGISTRY


def instantiate_provider(name: str, registry: PluginRegistry) -> object:
    """Resolve and instantiate a provider class or zero-argument factory."""
    implementation = registry.get(name)
    if isinstance(implementation, type):
        provider = implementation()
    elif callable(getattr(implementation, "complete", None)):
        provider = implementation
    elif callable(implementation):
        provider = implementation()
    else:
        raise TypeError("provider_implementation_invalid")
    if not callable(getattr(provider, "complete", None)):
        raise TypeError("provider_implementation_invalid")
    return provider
