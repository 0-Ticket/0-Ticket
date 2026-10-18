"""SIEM connector registry (box 3). In-repo adapters register here; others use entry points."""

from soc.plugins import PluginRegistry

from .direct import create_direct

SIEM_CONNECTORS = PluginRegistry("siem")
SIEM_CONNECTORS.register("direct", create_direct)
