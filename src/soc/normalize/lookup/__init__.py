"""Lookup providers (``lookups`` group) and the join step that uses them.

``[lookup] provider`` picks a registered provider; the core opens it with
``open_lookup`` and never names it. ``csv`` (box 5, the default) and ``none``
are registered here.
"""

import os
from collections.abc import Mapping

from soc.config import Settings
from soc.plugins import PluginRegistry

from .base import LookupProvider
from .none import create_none_lookup
from .table import create_csv_lookup

LOOKUPS = PluginRegistry("lookups")
LOOKUPS.register("csv", create_csv_lookup)
LOOKUPS.register("none", create_none_lookup)


def open_lookup(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> LookupProvider:
    """Open the provider ``[lookup] provider`` names."""
    environ = os.environ if environ is None else environ
    registry = LOOKUPS if registry is None else registry
    return registry.get(settings.lookup.provider)(settings, environ)
