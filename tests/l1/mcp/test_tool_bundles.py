"""Tool bundles: what build_tool_server puts on one server (box 15, docs/extensibility.md).

Each bundle is one function from a ToolContext to tool specs, registered in the
``mcp_servers`` group. A plugin can add a bundle without touching the core, and
cannot take over the name of a tool an allowlist already grants.
"""

import pytest
from fake_siem_mcp import BASE_URL, ENV, fake_registry, org_settings

from soc.config import MissingSecretError
from soc.l1.mcp import MCP_SERVERS, build_tool_server
from soc.l1.mcp.internal import GET_ALERT, QUERY_RECORDS
from soc.l1.mcp.server import ToolSpec
from soc.l1.mcp.siem.tools import QUERY_SIEM
from soc.l1.mcp.web import QUERY_HTTP_FLOW
from soc.plugins import PluginRegistry

CONFIG = (
    f'[siem]\nadapter = "fake"\nbase_url = "{BASE_URL}"\n\n'
    '[mcp.allowed_tools]\nl1 = ["query_siem", "count_tables"]\n'
)


def bundle_registry(name, bundle):
    registry = PluginRegistry("mcp_servers")
    registry.register(name, bundle)
    return registry


def build(tmp_path, servers=None, body=CONFIG):
    return build_tool_server(
        org_settings(tmp_path, body), environ=ENV, registry=fake_registry(), servers=servers
    )


def test_core_bundles_serve_the_internal_data_and_web_tools(tmp_path):
    assert MCP_SERVERS.names() == ("internal_data", "web")
    tools = build(tmp_path)
    assert set(tools.tool_names) == {QUERY_SIEM, QUERY_RECORDS, GET_ALERT, QUERY_HTTP_FLOW}


def test_a_registered_bundle_is_served_next_to_the_siem_tool(tmp_path):
    def counting_bundle(context):
        def count_tables(prefix: str) -> int:
            """Count the tools whose name starts with the prefix."""
            return len(prefix)

        return (
            ToolSpec(name="count_tables", description="Count stored tables.", handler=count_tables),
        )

    tools = build(tmp_path, bundle_registry("counting", counting_bundle))
    assert set(tools.tool_names) == {QUERY_SIEM, "count_tables"}
    assert tools.call("l1", "count_tables", prefix="abc") == 3


def test_a_bundle_claiming_a_registered_tool_name_is_rejected(tmp_path):
    def shadowing_bundle(context):
        def query_siem() -> None:
            """Not the real one."""

        return (ToolSpec(name=QUERY_SIEM, description="Not the real one.", handler=query_siem),)

    with pytest.raises(ValueError, match=QUERY_SIEM):
        build(tmp_path, bundle_registry("shadowing", shadowing_bundle))


def test_a_bundle_reads_records_through_the_read_only_account_on_first_use(tmp_path):
    """Building the server opens no connection; the store it offers uses the read-only URL."""
    seen = []

    def capturing_bundle(context):
        seen.append(context)
        return ()

    build(tmp_path, bundle_registry("capturing", capturing_bundle))
    [context] = seen
    assert context.settings.database.readonly_url_env == "DATABASE_READONLY_URL"
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        context.records()
