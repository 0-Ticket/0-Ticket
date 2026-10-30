"""SIEM connector registry (box 3). In-repo adapters register here; others use entry points."""

from soc.plugins import PluginRegistry

from .direct import MAPPING_AWARE_DIRECT_FACTORY
from .elastic import MAPPING_AWARE_ELASTIC_FACTORY

SIEM_CONNECTORS = PluginRegistry("siem")
SIEM_CONNECTORS.register("direct", MAPPING_AWARE_DIRECT_FACTORY)
SIEM_CONNECTORS.register("elastic", MAPPING_AWARE_ELASTIC_FACTORY)
