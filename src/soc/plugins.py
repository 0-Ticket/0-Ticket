"""Name-based registry for extension point implementations (docs/extensibility.md).

One registry per extension point. The core holds the interface and looks an
implementation up by the name the configuration gives it, so no core module
imports or branches on a specific implementation.
"""

import logging
from importlib.metadata import entry_points

ENTRY_POINT_PREFIX = "zero_ticket_soc"

logger = logging.getLogger(__name__)


class PluginNotFoundError(LookupError):
    """No implementation is registered under the requested name."""


class DuplicatePluginError(ValueError):
    """Another implementation already holds this name."""


class PluginRegistry:
    """Implementations of one extension point, found by name.

    This is not the registry of open contract values ("등록형 값",
    docs/data-contracts.md); those are data, these are objects.
    """

    def __init__(self, group: str):
        self.group = group
        self.load_errors: dict[str, str] = {}
        self._implementations: dict[str, object] = {}
        self._discovered = False

    def register(self, name: str, implementation: object) -> None:
        """Register an in-repo implementation. Re-registering the same object is a no-op."""
        existing = self._implementations.get(name)
        if existing is implementation:
            return
        if existing is not None:
            raise DuplicatePluginError(f"{self._label(name)} is already registered")
        self._implementations[name] = implementation

    def get(self, name: str) -> object:
        """Return the implementation the configuration selected by name."""
        self._discover()
        implementation = self._implementations.get(name)
        if implementation is None:
            available = ", ".join(self.names()) or "none"
            raise PluginNotFoundError(
                f"{self._label(name)} is not registered. Available: {available}"
            )
        return implementation

    def names(self) -> tuple[str, ...]:
        """Registered names, including external plugins once they are discovered."""
        self._discover()
        return tuple(sorted(self._implementations))

    def _label(self, name: str) -> str:
        return f"{self.group} plugin '{name}'"

    def _discover(self) -> None:
        """Load external plugins declared as entry points, once per registry.

        A plugin that fails to load, or that claims a name the repo already uses,
        is skipped and recorded in ``load_errors``: one broken package must not
        take the pipeline down with it.
        """
        # ponytail: no lock. Registries are built at startup, before worker threads.
        if self._discovered:
            return
        self._discovered = True
        for entry_point in entry_points(group=f"{ENTRY_POINT_PREFIX}.{self.group}"):
            if entry_point.name in self._implementations:
                self._fail(entry_point.name, "name already registered in the repo")
                continue
            try:
                self._implementations[entry_point.name] = entry_point.load()
            except Exception as error:  # Any import-time failure in third-party code.
                self._fail(entry_point.name, type(error).__name__)

    def _fail(self, name: str, reason: str) -> None:
        self.load_errors[name] = reason
        logger.warning("Skipped %s: %s", self._label(name), reason)
