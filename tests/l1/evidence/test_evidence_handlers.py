"""Built-in evidence handlers: siem_mcp through the MCP tool server (box 26 -> 15, K18, K59)
and lookup through the configured lookup provider (box 26 -> 5, K7, K59)."""

import logging

import pytest
from evidence_fakes import AGENT, FakeEvidenceQueue, FakeTicketStore, load
from fake_siem_mcp import BASE_URL, TOKEN, FakeSiemMcp
from specialist_fakes import context_for

from soc.config import load_config
from soc.contracts import AssetInfo, ContractValidationError, UserInfo
from soc.l1.evidence.handlers import default_handlers, lookup_handler, siem_mcp_handler
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.mcp.server import ToolNotAllowedError, ToolServer
from soc.l1.mcp.siem.tools import siem_tools
from soc.l1.tickets import TicketService
from soc.normalize.lookup import open_lookup
from soc.normalize.lookup.enricher import LookupEnricher
from soc.plugins import PluginRegistry

T = 1642500341120
NOW = 1791849600000
WEB_01 = AssetInfo.model_validate(
    {
        "match": "192.0.2.80",
        "hostname": "web-01",
        "criticality": 5,
        "owner": None,
        "zone": "dmz",
        "shared": False,
        "valid_from": None,
        "valid_to": None,
        "extensions": {},
    }
)
ALICE = UserInfo.model_validate(
    {"user": "alice@example.com", "dept": None, "privileged": False, "extensions": {}}
)


class RecordingLookup:
    """A lookup provider that knows web-01 (by IP or name) and alice, and records each call."""

    def __init__(self):
        self.calls = []

    def find_asset(self, value, at):
        self.calls.append(("asset", value, at))
        return WEB_01 if value in ("192.0.2.80", "web-01") else None

    def find_user(self, user, at):
        self.calls.append(("user", user, at))
        return ALICE if user == "alice@example.com" else None


def lookup_request(entity_type, value, at=T):
    return {"params": {"entity": {"type": entity_type, "value": value}, "at": at}}


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


def queue_service(server, settings, lookup=None):
    return EvidenceQueueService(
        FakeEvidenceQueue(),
        mcp=settings.mcp,
        max_retries=1,
        handlers=default_handlers(
            context_for(settings, server), lookup or RecordingLookup(), clock=lambda: NOW
        ),
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


def test_unreachable_siem_failure_reason_names_the_neutral_error(tmp_path):
    """#111: the failure reason says the SIEM was unreachable, and not which SIEM it was."""
    org = tmp_path / "org.toml"
    org.write_text('[mcp.allowed_tools]\nl1 = ["query_siem"]\n', encoding="utf-8")
    settings = load_config(org, environ={})
    adapter = FakeSiemMcp(BASE_URL, TOKEN, reachable=False)
    server = ToolServer(settings.mcp, siem_tools(adapter))
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
    assert failed["failure_reason"] == "SiemUnavailableError after 1 retries"
    assert len(adapter.queries) == 2


def test_default_handlers_cover_every_request_type(tmp_path):
    server, _, settings = tool_server(tmp_path, 'l1 = ["query_siem"]')
    handlers = default_handlers(context_for(settings, server), RecordingLookup())

    # The specialist handler itself is box 14's (tests/l1/specialists).
    assert set(handlers) == {"siem_mcp", "lookup", "specialist_agent"}


@pytest.mark.parametrize(
    ("entity_type", "value", "expected"),
    [
        ("ip", "192.0.2.80", {"asset": WEB_01, "user": None}),
        ("host", "web-01", {"asset": WEB_01, "user": None}),
        ("user", "alice@example.com", {"asset": None, "user": ALICE}),
        ("ip", "198.51.100.23", {"asset": None, "user": None}),
    ],
)
def test_lookup_handler_returns_c22_result_shape(entity_type, value, expected):
    lookup = RecordingLookup()
    handle = lookup_handler(LookupEnricher(lookup), clock=lambda: NOW)

    result = handle(lookup_request(entity_type, value), agent=AGENT)

    assert result == {
        key: None if v is None else v.model_dump(mode="json") for key, v in expected.items()
    }
    kind = "user" if entity_type == "user" else "asset"
    assert lookup.calls == [(kind, value, T)]


def test_lookup_handler_uses_now_when_at_is_null():
    lookup = RecordingLookup()
    handle = lookup_handler(LookupEnricher(lookup), clock=lambda: NOW)

    handle(lookup_request("ip", "192.0.2.80", at=None), agent=AGENT)

    assert lookup.calls == [("asset", "192.0.2.80", NOW)]


def test_unsupported_entity_type_completes_empty_and_warns_with_type_only(caplog):
    lookup = RecordingLookup()
    handle = lookup_handler(LookupEnricher(lookup), clock=lambda: NOW)

    with caplog.at_level(logging.WARNING, logger="soc.l1.evidence.handlers"):
        result = handle(lookup_request("hash", "secret-value-1234"), agent=AGENT)

    assert result == {"asset": None, "user": None}
    assert lookup.calls == []
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "hash" in record.getMessage()
    assert "secret-value-1234" not in record.getMessage()


def test_lookup_handler_rejects_provider_output_that_is_not_c4():
    class Broken(RecordingLookup):
        def find_asset(self, value, at):
            return {"match": value}

    with pytest.raises(ContractValidationError):
        lookup_handler(LookupEnricher(Broken()))(lookup_request("ip", "192.0.2.80"), agent=AGENT)


def test_lookup_request_completes_through_the_queue(tmp_path):
    server, _, settings = tool_server(tmp_path, 'l1 = ["query_siem"]')
    svc = queue_service(server, settings)
    svc.enqueue(
        agent=AGENT,
        requester_type="alert",
        requester_id="al_sample",
        request_type="lookup",
        params={"entity": {"type": "ip", "value": "192.0.2.80"}, "at": None},
    )

    done = svc.process_next()

    assert done["status"] == "completed"
    assert done["result"] == {"asset": WEB_01.model_dump(mode="json"), "user": None}


def test_enricher_and_queue_handler_use_the_same_provider(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text(
        '[lookup]\nprovider = "fake"\n[mcp.allowed_tools]\nl1 = ["query_siem"]\n', encoding="utf-8"
    )
    settings = load_config(org, environ={})
    shared = RecordingLookup()
    registry = PluginRegistry("lookups")
    registry.register("fake", lambda s, e: shared)
    provider = open_lookup(settings, environ={}, registry=registry)
    server = ToolServer(settings.mcp, siem_tools(RecordingAdapter()))

    LookupEnricher(provider).enrich(None, "192.0.2.80", None, T)
    default_handlers(context_for(settings, server), provider, clock=lambda: NOW)["lookup"](
        lookup_request("user", "alice@example.com"), agent=AGENT
    )

    assert shared.calls == [("asset", "192.0.2.80", T), ("user", "alice@example.com", T)]
