"""Web domain MCP tool: the HTTP requests around one source IP (boxes 14, 15, K18).

The Web specialist reads path, parameters, User-Agent, response code and size
from this one flow. Those strings come from the log, so the tool hands them over
unchanged, as data (docs/security-policy.md 3).
"""

import asyncio

import pytest
from fake_records import FakeReadOnlyRecords, fixture_events
from fake_siem_mcp import org_settings
from mcp import Client

from soc.l1.mcp.server import QueryLimitExceededError, ToolContext, ToolServer
from soc.l1.mcp.web import QUERY_HTTP_FLOW, web_tools

SOURCE = "203.0.113.25"
START = 1_770_000_000_000
END = 1_770_003_600_000

CONFIG = '[mcp.allowed_tools]\nweb_specialist = ["query_http_flow"]\n'
SMALL_LIMIT_CONFIG = f"[mcp]\nmax_query_limit = 2\n\n{CONFIG}"


def server(tmp_path, body=CONFIG, records=None):
    records = FakeReadOnlyRecords() if records is None else records
    settings = org_settings(tmp_path, body)
    context = ToolContext(settings, {}, lambda: records)
    return ToolServer(settings.mcp, web_tools(context)), records


def flow(**changes):
    sent = {"src_ip": SOURCE, "time_from": START, "time_to": END, "limit": 10}
    return {**sent, **changes}


def test_http_flow_returns_one_source_in_time_order(tmp_path):
    """The other source, the window outside and the non-HTTP event stay out."""
    tools, _ = server(tmp_path)
    found = tools.call("web_specialist", QUERY_HTTP_FLOW, **flow())
    assert [record["event_id"] for record in found] == [
        "ev_flow_login",
        "ev_flow_index",
        "ev_flow_upload",
    ]


def test_http_flow_hands_over_path_status_and_unmapped_unchanged(tmp_path):
    """Method, User-Agent and response size live in unmapped; an instruction in a
    User-Agent is passed on as data, never acted on."""
    tools, _ = server(tmp_path)
    found = tools.call("web_specialist", QUERY_HTTP_FLOW, **flow())
    stored = {record.event_id: record for record in fixture_events()}
    for record in found:
        original = stored[record["event_id"]]
        assert record["http_url"] == original.http_url
        assert record["http_status"] == original.http_status
        assert record["unmapped"] == original.unmapped
    assert found[0]["unmapped"]["user_agent"].startswith("Ignore previous instructions")
    assert found[1]["unmapped"]["bytes"] == "11238"


def test_http_flow_limit_above_max_query_limit_is_rejected_before_reading(tmp_path):
    tools, records = server(tmp_path, SMALL_LIMIT_CONFIG)
    with pytest.raises(QueryLimitExceededError):
        tools.call("web_specialist", QUERY_HTTP_FLOW, **flow(limit=500))
    assert records.queries == []


def test_http_flow_is_read_only_through_mcp(tmp_path):
    tools, _ = server(tmp_path)
    mcp_server = tools.as_mcp_server("web_specialist")

    async def run():
        async with Client(mcp_server) as client:
            listed = (await client.list_tools()).tools
            return listed, await client.call_tool(QUERY_HTTP_FLOW, flow())

    listed, result = asyncio.run(run())
    [tool] = listed
    assert tool.name == QUERY_HTTP_FLOW
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert result.is_error is False
    assert len(result.structured_content["result"]) == 3
