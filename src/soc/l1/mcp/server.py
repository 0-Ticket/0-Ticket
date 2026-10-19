"""MCP tool server: read-only tools behind a per-agent allowlist (box 15, K18, D-041).

Built with the official MCP SDK. Every call goes through ``ToolServer.call``,
which checks the allowlist from the settings and the query limit before the tool
runs, so the protocol path and an in-process call are gated by the same code.
``as_mcp_server`` fixes the agent when the server is built and exposes only that
agent's tools, so the agent is never a tool argument a caller could change.
"""

import functools
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from soc.config import McpSettings, Settings
from soc.store.records.base import RecordStore

logger = logging.getLogger(__name__)

SERVER_NAME = "zero-ticket-soc"


class ToolNotAllowedError(PermissionError):
    """This agent's allowlist does not carry the tool that was asked for."""


class UnknownToolError(LookupError):
    """No tool is registered under that name."""


class QueryLimitExceededError(ValueError):
    """The call asked for more records than ``mcp.max_query_limit`` allows."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One read-only tool.

    ``handler`` keeps its own typed signature, which the SDK turns into the tool's
    input schema. ``limit_argument`` names the argument the core caps with
    ``mcp.max_query_limit``; a tool that returns no record list leaves it None.
    """

    name: str
    description: str
    handler: Callable[..., Any]
    limit_argument: str | None = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What one bundle of tools is built from (docs/extensibility.md).

    ``records`` opens the read-only Alert/Event store the first time a tool
    actually reads, so building a server costs no database connection. Options
    come from ``settings``; secrets are read from ``environ`` through
    ``soc.config.read_secret``.
    """

    settings: Settings
    environ: Mapping[str, str]
    records: Callable[[], RecordStore]


class ToolServer:
    """The tools of this process, and which agent may call which."""

    def __init__(
        self,
        settings: McpSettings,
        tools: Sequence[ToolSpec],
        name: str = SERVER_NAME,
    ):
        self._settings = settings
        self._tools: dict[str, ToolSpec] = {}
        for spec in tools:
            # Two bundles under one name would let the later one answer for a tool
            # an allowlist already grants, so a clash fails at startup.
            if spec.name in self._tools:
                raise ValueError(f"tool '{spec.name}' is registered twice")
            self._tools[spec.name] = spec
        self._name = name

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Every registered tool, whoever may call it."""
        return tuple(self._tools)

    def allowed_tools(self, agent: str) -> tuple[str, ...]:
        """The registered tools this agent's allowlist grants. Unknown agent: none."""
        granted = set(self._settings.allowed_tools.get(agent, ()))
        return tuple(name for name in self._tools if name in granted)

    def call(self, agent: str, tool: str, **arguments: Any) -> Any:
        """The one way into a tool: allowlist, then limit, then the tool itself."""
        if tool not in self._settings.allowed_tools.get(agent, ()):
            logger.warning("Refused tool '%s' for agent '%s': not in its allowlist", tool, agent)
            raise ToolNotAllowedError(f"agent '{agent}' may not call tool '{tool}'")
        spec = self._tools.get(tool)
        if spec is None:
            raise UnknownToolError(f"tool '{tool}' is not registered")
        self._check_limit(spec, arguments)
        return spec.handler(**arguments)

    def as_mcp_server(self, agent: str) -> MCPServer:
        """An MCP server carrying only this agent's tools, each marked read-only."""
        server = MCPServer(self._name)
        for name in self.allowed_tools(agent):
            spec = self._tools[name]
            server.tool(
                name=spec.name,
                description=spec.description,
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
            )(self._gated(agent, spec))
        return server

    def _check_limit(self, spec: ToolSpec, arguments: Mapping[str, Any]) -> None:
        if spec.limit_argument is None:
            return
        asked = arguments.get(spec.limit_argument)
        if isinstance(asked, int) and asked > self._settings.max_query_limit:
            raise QueryLimitExceededError(
                f"{spec.limit_argument} {asked} is above mcp.max_query_limit "
                f"{self._settings.max_query_limit}"
            )

    def _gated(self, agent: str, spec: ToolSpec) -> Callable[..., Any]:
        """The handler with this agent fixed. ``wraps`` keeps the signature the SDK reads."""

        @functools.wraps(spec.handler)
        def tool(**arguments: Any) -> Any:
            return self.call(agent, spec.name, **arguments)

        return tool
