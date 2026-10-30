"""SIEM connector registry. In-repo adapters register here; others use entry points."""

from soc.plugins import PluginRegistry

from .direct import create_direct
from .elastic import create_elastic

SIEM_CONNECTORS = PluginRegistry("siem")
SIEM_CONNECTORS.register("direct", create_direct)
SIEM_CONNECTORS.register("elastic", create_elastic)
