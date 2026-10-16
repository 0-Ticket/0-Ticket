"""Name-based registry for extension point implementations (docs/extensibility.md).

One registry per extension point. The core holds the interface and looks an
implementation up by the name the configuration gives it, so no core module
imports or branches on a specific implementation.
"""

import logging
from importlib.metadata import EntryPoint, entry_points

ENTRY_POINT_PREFIX = "zero_ticket_soc"

# The extension points of docs/extensibility.md, which are core structure, not
# implementations: a new SIEM adapter or vector store needs no change here.
# Extension points served by files instead of entry points are not listed.
EXTENSION_POINT_GROUPS = frozenset(
    {
        "sources",
        "raw_stores",
        "siem",
        "lookups",
        "stores",
        "vector_stores",
        "embedders",
        "llm_providers",
        "specialists",
        "mcp_servers",
        "review_channels",
        "case_systems",
        "rule_targets",
    }
)

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
        if group not in EXTENSION_POINT_GROUPS:
            defined = ", ".join(sorted(EXTENSION_POINT_GROUPS))
            raise ValueError(
                f"'{group}' is not an extension point of docs/extensibility.md. Defined: {defined}"
            )
        self.group = group
        self.load_errors: dict[str, str] = {}
        self._implementations: dict[str, object] = {}
        self._external: set[str] = set()
        self._discovered = False

    def register(self, name: str, implementation: object) -> None:
        """Register an in-repo implementation. Re-registering the same object is a no-op.

        An in-repo name always beats an external plugin, whichever was seen first,
        so discovery order cannot change which implementation a name resolves to.
        """
        existing = self._implementations.get(name)
        if existing is implementation:
            return
        if name in self._external:
            self._external.discard(name)
            self._implementations[name] = implementation
            self._fail(name, "name already registered in the repo")
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
        declared: dict[str, list[EntryPoint]] = {}
        for entry_point in entry_points(group=f"{ENTRY_POINT_PREFIX}.{self.group}"):
            declared.setdefault(entry_point.name, []).append(entry_point)
        self._reject_external_duplicates(declared)
        self._discovered = True
        for name, points in sorted(declared.items()):
            if name in self._implementations:
                self._fail(name, "name already registered in the repo")
                continue
            try:
                self._implementations[name] = points[0].load()
            except Exception as error:  # Any import-time failure in third-party code.
                self._fail(name, type(error).__name__)
            else:
                self._external.add(name)

    def _reject_external_duplicates(self, declared: dict[str, list[EntryPoint]]) -> None:
        """Two external packages claiming one name is not recoverable: fail, never pick one.

        This runs before anything is loaded or recorded, so the failure and its
        message are the same whatever order the packages were discovered in.
        """
        collisions = {
            name: sorted(self._source(point) for point in points)
            for name, points in declared.items()
            if len(points) > 1 and name not in self._implementations
        }
        if collisions:
            raise DuplicatePluginError(
                "; ".join(
                    f"{self._label(name)} is declared by {', '.join(sources)}"
                    for name, sources in sorted(collisions.items())
                )
            )

    @staticmethod
    def _source(entry_point: EntryPoint) -> str:
        return entry_point.dist.name if entry_point.dist else "an unknown package"

    def _fail(self, name: str, reason: str) -> None:
        self.load_errors[name] = reason
        logger.warning("Skipped %s: %s", self._label(name), reason)
