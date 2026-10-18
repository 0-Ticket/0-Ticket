"""SIEM MCP adapter registry (box 15, D-035).

Adapters kept in this repo register here; an organization's own adapter arrives
as an entry point in the ``zero_ticket_soc.siem_mcp_adapters`` group. Nothing is
registered yet: the adapter for the chosen SIEM lands with its environment.
"""

from soc.plugins import PluginRegistry

SIEM_MCP_ADAPTERS = PluginRegistry("siem_mcp_adapters")
