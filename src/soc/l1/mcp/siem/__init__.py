"""SIEM MCP adapter registry (box 15, D-035).

Adapters kept in this repo register here; an organization's own adapter arrives
as an entry point in the ``zero_ticket_soc.siem_mcp_adapters`` group. Each name
matches the box 3 connector for the same SIEM (D-037): ``direct`` (development
and demo) and ``elastic`` (Elasticsearch + Kibana Security, #99). The Wazuh
adapter lands with its environment.
"""

from soc.plugins import PluginRegistry

from .direct import MAPPING_AWARE_DIRECT_MCP_FACTORY
from .elastic import MAPPING_AWARE_ELASTIC_MCP_FACTORY

SIEM_MCP_ADAPTERS = PluginRegistry("siem_mcp_adapters")
SIEM_MCP_ADAPTERS.register("direct", MAPPING_AWARE_DIRECT_MCP_FACTORY)
SIEM_MCP_ADAPTERS.register("elastic", MAPPING_AWARE_ELASTIC_MCP_FACTORY)
