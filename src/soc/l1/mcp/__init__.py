"""MCP tools (box 15): the only path from an agent to a tool.

``build_tool_server`` reads the settings, resolves the SIEM MCP adapter the same
``siem.adapter`` name selects for the connector (D-037), adds every tool bundle
registered in the ``mcp_servers`` group, and returns the server that enforces the
per-agent allowlist.

A bundle is one function from a ``ToolContext`` to tool specs, so a new domain's
tools are one function and one registration (docs/extensibility.md).
"""

import functools
import os
from collections.abc import Mapping

from soc.config import ConfigError, Settings
from soc.l1.mcp.internal import internal_data_tools
from soc.l1.mcp.server import (
    QueryLimitExceededError as QueryLimitExceededError,
)
from soc.l1.mcp.server import (
    ToolContext as ToolContext,
)
from soc.l1.mcp.server import (
    ToolNotAllowedError as ToolNotAllowedError,
)
from soc.l1.mcp.server import (
    ToolServer as ToolServer,
)
from soc.l1.mcp.server import (
    ToolSpec as ToolSpec,
)
from soc.l1.mcp.server import (
    UnknownToolError as UnknownToolError,
)
from soc.l1.mcp.siem import SIEM_MCP_ADAPTERS
from soc.l1.mcp.siem.tools import siem_tools
from soc.l1.mcp.web import web_tools
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.records.base import READONLY_STORE_KIND

MCP_SERVERS = PluginRegistry("mcp_servers")
MCP_SERVERS.register("internal_data", internal_data_tools)
MCP_SERVERS.register("web", web_tools)


def build_tool_server(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
    servers: PluginRegistry | None = None,
) -> ToolServer:
    """Build the tool server: the SIEM MCP adapter the settings select, plus every bundle.

    Raises if no adapter is selected, so a misconfigured deployment fails at
    startup instead of leaving an agent without the tools it expects.
    """
    environ = os.environ if environ is None else environ
    registry = SIEM_MCP_ADAPTERS if registry is None else registry
    servers = MCP_SERVERS if servers is None else servers
    siem = settings.siem
    if not siem.adapter:
        raise ConfigError(
            "Setting 'siem.adapter' is empty: choose a registered SIEM adapter in the "
            "organization settings (ZT_CONFIG)"
        )
    factory = registry.get(siem.adapter)
    context = ToolContext(settings, environ, _readonly_records(settings, environ))
    tools = list(siem_tools(factory(siem, environ)))
    for name in servers.names():
        tools.extend(servers.get(name)(context))
    return ToolServer(settings.mcp, tools)


def _readonly_records(settings: Settings, environ: Mapping[str, str]):
    """Open the read-only Alert/Event store on first use, then reuse it."""

    @functools.cache
    def records():
        return open_store(READONLY_STORE_KIND, settings, environ)

    return records
