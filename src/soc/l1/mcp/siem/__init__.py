"""SIEM MCP adapter registry (box 15, D-035).

Adapters kept in this repo register here; an organization's own adapter arrives
as an entry point in the ``zero_ticket_soc.siem_mcp_adapters`` group. Only the
``direct`` adapter (development and demo, D-037) ships here: the adapter for the
chosen SIEM lands with its environment.
"""

from soc.plugins import PluginRegistry

from .direct import create_direct_mcp

SIEM_MCP_ADAPTERS = PluginRegistry("siem_mcp_adapters")
SIEM_MCP_ADAPTERS.register("direct", create_direct_mcp)
