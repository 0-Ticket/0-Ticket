"""The siem_mcp handler reads through the MCP tool server (box 26 -> 15, K18, K59)."""

import pytest
from evidence_fakes import AGENT, FakeEvidenceQueue, FakeTicketStore, load

from soc.config import load_config
from soc.l1.evidence.handlers import default_handlers, siem_mcp_handler
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.mcp.server import ToolNotAllowedError, ToolServer
from soc.l1.mcp.siem.tools import siem_tools
from soc.l1.tickets import TicketService

RECORD = {
    "kind": "alert",
    "scenario": "web_sqli",
    "raw_ids": ["raw_web_access.log_2"],
    "fields": {"time": 1770000600000, "src_ip": "203.0.113.10", "url": "/search"},
}


class RecordingAdapter:
    """A SIEM MCP adapter that answers every query with RECORD."""

    def __init__(self):
        self.queries = []

    def query(self, query):
        self.queries.append(query)
        return (RECORD,)

    def health_check(self):
        raise AssertionError("not used")


def tool_server(tmp_path, allowed):
    org = tmp_path / "org.toml"
    org.write_text(f"[mcp.allowed_tools]\n{allowed}\n", encoding="utf-8")
    settings = load_config(org, environ={})
    adapter = RecordingAdapter()
    return ToolServer(settings.mcp, siem_tools(adapter)), adapter, settings


def test_siem_mcp_handler_calls_query_siem_with_requesting_agent(tmp_path):
    server, adapter, _ = tool_server(tmp_path, 'l1 = ["query_siem"]')
    request = load("siem_mcp_alert_request.json")

    result = siem_mcp_handler(server)(request, agent=AGENT)

    (query,) = adapter.queries
    params = request["params"]
    assert (query.entity.type, query.entity.value) == ("ip", "203.0.113.10")
    assert (query.kind, query.start_at, query.end_at, query.limit) == (
        params["kind"],
        params["start_at"],
        params["end_at"],
        params["limit"],
    )
    (record,) = result["records"]
    assert record["source_record_id"].startswith("src_")
    assert record["fields"] == RECORD["fields"]


def test_agent_without_query_siem_is_refused(tmp_path):
    server, adapter, _ = tool_server(tmp_path, 'l2 = ["query_siem"]')

    with pytest.raises(ToolNotAllowedError):
        siem_mcp_handler(server)(load("siem_mcp_alert_request.json"), agent=AGENT)
    assert adapter.queries == []


def queue_service(server, settings):
    return EvidenceQueueService(
        FakeEvidenceQueue(),
        mcp=settings.mcp,
        max_retries=1,
        handlers=default_handlers(server),
        tickets=TicketService(FakeTicketStore()),
    )


def test_siem_mcp_request_completes_with_c2_records(tmp_path):
    server, _, settings = tool_server(tmp_path, 'l1 = ["query_siem"]')
    svc = queue_service(server, settings)
    params = load("siem_mcp_alert_request.json")["params"]
    svc.enqueue(
        agent=AGENT,
        requester_type="alert",
        requester_id="al_sample",
        request_type="siem_mcp",
        params=params,
    )

    done = svc.process_next()

    assert done["status"] == "completed"
    assert done["result"]["records"][0]["scenario"] == "web_sqli"


def test_agent_without_query_siem_fails_the_request(tmp_path):
    server, adapter, settings = tool_server(tmp_path, 'l2 = ["query_siem"]')
    svc = queue_service(server, settings)
    svc.enqueue(
        agent=AGENT,
        requester_type="alert",
        requester_id="al_sample",
        request_type="siem_mcp",
        params=load("siem_mcp_alert_request.json")["params"],
    )

    failed = svc.process_next()

    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "ToolNotAllowedError after 1 retries"
    assert adapter.queries == []


def test_default_handlers_cover_only_siem_mcp(tmp_path):
    server, _, _ = tool_server(tmp_path, 'l1 = ["query_siem"]')
    # lookup waits for box 5 (1-6) and specialist_agent for box 14 (3-4).
    assert set(default_handlers(server)) == {"siem_mcp"}
