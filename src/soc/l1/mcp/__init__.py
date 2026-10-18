"""MCP tools (box 15): the only path from an agent to a tool.

``build_tool_server`` reads the settings, resolves the SIEM MCP adapter the same
``siem.adapter`` name selects for the connector (D-037), and returns the server
that enforces the per-agent allowlist.
"""

import os
from collections.abc import Mapping

from soc.config import ConfigError, Settings
from soc.l1.mcp.server import (
    QueryLimitExceededError as QueryLimitExceededError,
)
from soc.l1.mcp.server import (
    ToolNotAllowedError as ToolNotAllowedError,
)
from soc.l1.mcp.server import (
    ToolServer as ToolServer,
)
from soc.l1.mcp.server import (
    UnknownToolError as UnknownToolError,
)
from soc.l1.mcp.siem import SIEM_MCP_ADAPTERS
from soc.l1.mcp.siem.tools import siem_tools
from soc.plugins import PluginRegistry


def build_tool_server(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> ToolServer:
    """Build the tool server with the SIEM MCP adapter the settings select.

    Raises if no adapter is selected, so a misconfigured deployment fails at
    startup instead of leaving an agent without the tools it expects.
    """
    environ = os.environ if environ is None else environ
    registry = SIEM_MCP_ADAPTERS if registry is None else registry
    siem = settings.siem
    if not siem.adapter:
        raise ConfigError(
            "Setting 'siem.adapter' is empty: choose a registered SIEM adapter in the "
            "organization settings (ZT_CONFIG)"
        )
    factory = registry.get(siem.adapter)
    return ToolServer(settings.mcp, siem_tools(factory(siem, environ)))
