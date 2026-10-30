"""Internal data MCP tools: read stored C5 and C13 behind the allowlist (boxes 19, 28, 31, 42, K18).

The tools are built on the read-only record store, so these tests pass a fake
that only reads. Entity field, kind and limit are checked before anything is read.
"""

import pytest
from fake_records import FakeReadOnlyRecords
from fake_siem_mcp import org_settings

from soc.l1.mcp.internal import GET_ALERT, QUERY_RECORDS, internal_data_tools
from soc.l1.mcp.server import QueryLimitExceededError, ToolContext, ToolNotAllowedError, ToolServer

SOURCE = "203.0.113.25"
START = 1_770_000_000_000
END = 1_770_003_600_000

CONFIG = (
    '[mcp.allowed_tools]\nl1 = ["query_records", "get_alert"]\nweb_specialist = ["query_records"]\n'
)
SMALL_LIMIT_CONFIG = f"[mcp]\nmax_query_limit = 2\n\n{CONFIG}"


def server(tmp_path, body=CONFIG, records=None):
    records = FakeReadOnlyRecords() if records is None else records
    settings = org_settings(tmp_path, body)
    context = ToolContext(settings, {}, lambda: records)
    return ToolServer(settings.mcp, internal_data_tools(context)), records


def query(**changes):
    sent = {
        "field": "src_ip",
        "value": SOURCE,
        "kind": "alert",
        "time_from": START,
        "time_to": END,
        "limit": 10,
    }
    return {**sent, **changes}


def test_query_records_returns_alerts_of_one_entity_in_the_window(tmp_path):
    tools, _ = server(tmp_path)
    found = tools.call("l1", QUERY_RECORDS, **query())
    assert [record["alert_id"] for record in found] == ["al_flow_scan", "al_flow_sqli"]
    assert all(record["source_record_id"].startswith("src_") for record in found)


def test_query_records_returns_events_of_one_entity_in_the_window(tmp_path):
    tools, _ = server(tmp_path)
    found = tools.call("l1", QUERY_RECORDS, **query(kind="event"))
    assert [record["event_id"] for record in found] == [
        "ev_flow_login",
        "ev_flow_index",
        "ev_flow_upload",
        "ev_flow_logon",
    ]


def test_query_records_rejects_an_unknown_kind_before_reading(tmp_path):
    tools, records = server(tmp_path)
    with pytest.raises(ValueError, match="alert"):
        tools.call("l1", QUERY_RECORDS, **query(kind="incident"))
    assert records.queries == []


def test_query_records_rejects_a_field_that_is_not_an_entity_column(tmp_path):
    tools, _ = server(tmp_path)
    with pytest.raises(ValueError, match="src_ip"):
        tools.call("l1", QUERY_RECORDS, **query(field="http_url"))


def test_query_records_limit_above_max_query_limit_is_rejected_before_reading(tmp_path):
    tools, records = server(tmp_path, SMALL_LIMIT_CONFIG)
    with pytest.raises(QueryLimitExceededError):
        tools.call("l1", QUERY_RECORDS, **query(limit=500))
    assert records.queries == []
    assert len(tools.call("l1", QUERY_RECORDS, **query(limit=2))) == 2


def test_get_alert_returns_the_stored_record_and_none_for_an_unknown_id(tmp_path):
    tools, _ = server(tmp_path)
    found = tools.call("l1", GET_ALERT, alert_id="al_flow_sqli")
    assert found["rule_id"] == "2019401"
    assert found["http_url"] == "/index.php?id=1 UNION SELECT 1"
    assert tools.call("l1", GET_ALERT, alert_id="al_missing") is None


def test_get_alert_is_not_granted_to_every_agent(tmp_path):
    tools, records = server(tmp_path)
    with pytest.raises(ToolNotAllowedError, match="web_specialist"):
        tools.call("web_specialist", GET_ALERT, alert_id="al_flow_sqli")
    assert records.queries == []
