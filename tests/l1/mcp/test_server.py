"""MCP tool server: read-only tools behind a per-agent allowlist (box 15, K18).

The protocol tests drive the server through the official SDK's in-process client,
so what they check is what an agent would get, not just what the gate returns.
Each one wraps the async client in asyncio.run, which needs no pytest plugin.
"""

import asyncio

import pytest
from fake_siem_mcp import BASE_URL, ENV, TOKEN, FakeSiemMcp, fake_registry, org_settings
from mcp import Client

from soc.config import load_config
from soc.l1.mcp import build_tool_server
from soc.l1.mcp.server import ToolNotAllowedError, UnknownToolError

SOURCE = "203.0.113.10"
START = 1_770_000_000_000
END = 1_770_003_600_000
NO_TOOLS_CONFIG = f'[siem]\nadapter = "fake"\nbase_url = "{BASE_URL}"\n'
SMALL_LIMIT_CONFIG = (
    f'[siem]\nadapter = "fake"\nbase_url = "{BASE_URL}"\n\n'
    "[mcp]\nmax_query_limit = 2\n\n"
    '[mcp.allowed_tools]\nl1 = ["query_siem"]\n'
)


def arguments(**changes):
    sent = {
        "entity_type": "ip",
        "entity_value": SOURCE,
        "kind": "alert",
        "start_at": START,
        "end_at": END,
        "limit": 10,
    }
    return {**sent, **changes}


def server_with(tmp_path, body=None, adapter=None):
    adapter = adapter or FakeSiemMcp(BASE_URL, TOKEN)
    settings = org_settings(tmp_path) if body is None else org_settings(tmp_path, body)
    registry = fake_registry(lambda siem_settings, environ: adapter)
    return build_tool_server(settings, environ=ENV, registry=registry), adapter


def call_through_protocol(mcp_server, tool, sent):
    async def run():
        async with Client(mcp_server) as client:
            return await client.call_tool(tool, sent)

    return asyncio.run(run())


def tools_through_protocol(mcp_server):
    async def run():
        async with Client(mcp_server) as client:
            return (await client.list_tools()).tools

    return asyncio.run(run())


def test_allowed_tool_works_through_mcp_client(tmp_path):
    server, _ = server_with(tmp_path)
    result = call_through_protocol(server.as_mcp_server("l1"), "query_siem", arguments())
    assert result.is_error is False
    records = result.structured_content["result"]
    assert [record["scenario"] for record in records] == ["web_scan", "web_sqli", "web_upload"]
    assert all(record["source_record_id"].startswith("src_") for record in records)


def test_tool_not_in_allowlist_is_rejected_through_mcp(tmp_path):
    server, adapter = server_with(tmp_path)
    result = call_through_protocol(server.as_mcp_server("l2"), "query_siem", arguments())
    assert result.is_error is True
    assert adapter.queries == []


def test_agent_without_allowlist_exposes_no_tools(tmp_path):
    server, adapter = server_with(tmp_path, NO_TOOLS_CONFIG)
    assert tools_through_protocol(server.as_mcp_server("l1")) == []
    result = call_through_protocol(server.as_mcp_server("l1"), "query_siem", arguments())
    assert result.is_error is True
    assert adapter.queries == []


def test_server_exposes_only_query_siem_as_read_only(tmp_path):
    """No response tool exists, and the one tool declares itself read-only."""
    server, _ = server_with(tmp_path)
    [tool] = tools_through_protocol(server.as_mcp_server("l1"))
    assert tool.name == "query_siem"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert server.tool_names == ("query_siem",)


def test_allowlist_is_per_agent(tmp_path):
    server, _ = server_with(tmp_path)
    assert server.allowed_tools("l1") == ("query_siem",)
    assert server.allowed_tools("l2") == ()
    assert server.allowed_tools("not_configured") == ()


def test_direct_call_rejects_a_tool_the_agent_may_not_use(tmp_path):
    server, adapter = server_with(tmp_path)
    with pytest.raises(ToolNotAllowedError, match="l2"):
        server.call("l2", "query_siem", **arguments())
    assert adapter.queries == []


def test_unknown_tool_name_is_rejected(tmp_path):
    body = (
        f'[siem]\nadapter = "fake"\nbase_url = "{BASE_URL}"\n\n'
        '[mcp.allowed_tools]\nl1 = ["query_siem", "block_ip"]\n'
    )
    server, _ = server_with(tmp_path, body)
    with pytest.raises(UnknownToolError, match="block_ip"):
        server.call("l1", "block_ip")


def test_limit_above_max_query_limit_is_rejected_before_the_adapter(tmp_path):
    server, adapter = server_with(tmp_path, SMALL_LIMIT_CONFIG)
    result = call_through_protocol(server.as_mcp_server("l1"), "query_siem", arguments(limit=500))
    assert result.is_error is True
    assert adapter.queries == []
    assert len(server.call("l1", "query_siem", **arguments(limit=2))) == 2


def test_limit_below_one_is_rejected(tmp_path):
    server, adapter = server_with(tmp_path)
    with pytest.raises(ValueError):
        server.call("l1", "query_siem", **arguments(limit=0))
    assert adapter.queries == []


def test_window_that_ends_before_it_starts_is_rejected(tmp_path):
    server, adapter = server_with(tmp_path)
    with pytest.raises(ValueError):
        server.call("l1", "query_siem", **arguments(start_at=END, end_at=START))
    assert adapter.queries == []


def test_unknown_kind_is_rejected_through_mcp(tmp_path):
    server, adapter = server_with(tmp_path)
    result = call_through_protocol(
        server.as_mcp_server("l1"), "query_siem", arguments(kind="incident")
    )
    assert result.is_error is True
    assert adapter.queries == []


def test_default_settings_allow_no_agent_any_tool():
    """The shipped default denies everything; the organization settings grant tools."""
    assert load_config(environ={}).mcp.allowed_tools == {}
