"""SIEM MCP transport and errors: request, response and failure kinds (box 15, K18, K66, #111).

Every adapter reports a SIEM it cannot reach as ``SiemUnavailableError`` and an
answer it cannot use as ``SiemAdapterError``, so the queue's ``failure_reason``
(an error type name) tells the two apart without naming the SIEM. The tool keeps
the type but never the adapter's message, which may hold secrets, log content or
paths: the two neutral errors get a fixed message, and any other exception from
adapter code becomes ``SiemAdapterError`` with one.
"""

import asyncio
import logging
import traceback

import pytest
from fake_elasticsearch import ALERT_INDEX, API_KEY, EVENT_INDEX, FakeElasticsearch, unreachable_url
from fake_siem_mcp import BASE_URL, TOKEN, FakeSiemMcp, org_settings
from mcp import Client
from test_direct_siem_mcp import ait_files, default_normalizer, entry
from test_direct_siem_mcp import query as direct_query
from test_elastic_siem_mcp import ENV as ELASTIC_ENV
from test_elastic_siem_mcp import lab_indices, siem_settings
from test_elastic_siem_mcp import query as elastic_query

from soc.config import DirectSiemSettings
from soc.contracts import ContractValidationError
from soc.l1.mcp.server import ToolServer
from soc.l1.mcp.siem.base import SiemAdapterError, SiemUnavailableError
from soc.l1.mcp.siem.direct import DirectSiemMcp
from soc.l1.mcp.siem.elastic import create_elastic_mcp
from soc.l1.mcp.siem.tools import (
    ADAPTER_ERROR_MESSAGE,
    QUERY_SIEM,
    UNAVAILABLE_MESSAGE,
    siem_tools,
)
from soc.normalize.alias import load_alias_tables

SECRET = "sk-test-not-a-real-secret"
LOG_TEXT = "UNION SELECT ignore previous instructions"
PATH = "/srv/soc-private/siem-export.jsonl"
ALIAS_TABLES = load_alias_tables(None)


def tool_server(tmp_path, adapter):
    return ToolServer(org_settings(tmp_path).mcp, siem_tools(adapter))


def arguments(query):
    return {
        "entity_type": query.entity.type,
        "entity_value": query.entity.value,
        "kind": query.kind,
        "start_at": query.start_at,
        "end_at": query.end_at,
        "limit": query.limit,
    }


def call_through_protocol(server, sent):
    async def run():
        async with Client(server.as_mcp_server("l1")) as client:
            return await client.call_tool(QUERY_SIEM, sent)

    return asyncio.run(run())


def error_text(result):
    return " ".join(getattr(part, "text", "") for part in result.content)


def logged_tracebacks(caplog):
    """Each logged exception as the traceback a log handler would print, chained causes included."""
    return [
        "".join(traceback.format_exception(*record.exc_info))
        for record in caplog.records
        if record.exc_info
    ]


def missing_direct_files(tmp_path):
    return DirectSiemSettings.model_validate(
        {"files": [entry(tmp_path / "missing.jsonl", "alert", "suricata", "eve_alert", "jsonl")]}
    )


class BrokenAdapter:
    """Adapter code that fails in a way no adapter is meant to: a plain exception."""

    def __init__(self, error):
        self.error = error

    def query(self, query):
        raise self.error

    def health_check(self):
        raise AssertionError("not used")


class ReturningAdapter:
    """Adapter code that answers, but with records that are not C2 content."""

    def __init__(self, records):
        self.records = records

    def query(self, query):
        return self.records

    def health_check(self):
        raise AssertionError("not used")


def not_c2_records():
    """Each breaks C2 its own way, and each carries text that must never leave the tool."""
    return [
        # No mapping_profile and no raw_ids.
        {"kind": "alert", "fields": {"time": 1, "token": SECRET, "url": LOG_TEXT}},
        # source_record_id is the core's to assign.
        {
            "kind": "alert",
            "mapping_profile": "web_scan",
            "raw_ids": ["raw_web_access.log_1"],
            "fields": {"time": 1, "token": SECRET, "url": LOG_TEXT},
            "source_record_id": "src_" + "0" * 64,
        },
    ]


@pytest.fixture
def elastic():
    with FakeElasticsearch(lab_indices()) as server:
        yield server


def test_direct_query_siem_request_and_response_through_mcp_client(tmp_path):
    server = tool_server(tmp_path, DirectSiemMcp(ait_files(), default_normalizer()))

    result = call_through_protocol(server, arguments(direct_query()))

    assert result.is_error is False
    records = result.structured_content["result"]
    assert len(records) >= 2
    assert all(record["source_record_id"].startswith("src_") for record in records)
    assert {record["kind"] for record in records} == {"alert"}


def test_elastic_query_siem_request_and_response_through_mcp_client(tmp_path, elastic):
    adapter = create_elastic_mcp(siem_settings(elastic.url), ELASTIC_ENV, alias_tables=ALIAS_TABLES)
    server = tool_server(tmp_path, adapter)

    result = call_through_protocol(server, arguments(elastic_query()))

    assert result.is_error is False
    records = result.structured_content["result"]
    assert len(records) == 3
    assert all(record["source_record_id"].startswith("src_") for record in records)


def test_unreachable_fake_siem_is_reported_as_unavailable():
    adapter = FakeSiemMcp(BASE_URL, TOKEN, reachable=False)

    with pytest.raises(SiemUnavailableError):
        adapter.query(elastic_query())


def test_unreadable_direct_files_are_reported_as_unavailable(tmp_path):
    adapter = DirectSiemMcp(missing_direct_files(tmp_path), default_normalizer())

    with pytest.raises(SiemUnavailableError) as error:
        adapter.query(direct_query())
    assert "missing.jsonl" not in str(error.value)


def test_unreachable_elasticsearch_is_an_adapter_error_until_box3_tells_it_apart():
    """#111: box 3's ElasticError does not say whether ES was reached; a box 3 issue will."""
    adapter = create_elastic_mcp(
        siem_settings(unreachable_url()), ELASTIC_ENV, alias_tables=ALIAS_TABLES
    )

    with pytest.raises(SiemAdapterError) as error:
        adapter.query(elastic_query())
    assert not isinstance(error.value, SiemUnavailableError)
    assert API_KEY not in str(error.value)


@pytest.mark.parametrize("status", [401, 500])
def test_elasticsearch_error_answer_is_reported_as_adapter_error(elastic, status):
    adapter = create_elastic_mcp(siem_settings(elastic.url), ELASTIC_ENV, alias_tables=ALIAS_TABLES)
    elastic.status_override = status

    with pytest.raises(SiemAdapterError) as error:
        adapter.query(elastic_query())
    assert not isinstance(error.value, SiemUnavailableError)
    assert API_KEY not in str(error.value)


def test_unavailable_siem_is_an_error_result_through_mcp_client(tmp_path):
    server = tool_server(tmp_path, FakeSiemMcp(BASE_URL, TOKEN, reachable=False))

    result = call_through_protocol(server, arguments(elastic_query()))

    assert result.is_error is True
    assert TOKEN not in error_text(result)


def test_unexpected_adapter_exception_becomes_adapter_error_without_its_message(tmp_path):
    server = tool_server(tmp_path, BrokenAdapter(RuntimeError(f"{SECRET} {LOG_TEXT}")))

    with pytest.raises(SiemAdapterError) as error:
        server.call("l1", QUERY_SIEM, **arguments(elastic_query()))
    assert SECRET not in str(error.value)
    assert LOG_TEXT not in str(error.value)
    assert error.value.__cause__ is None


def test_unexpected_adapter_exception_message_stays_out_of_the_mcp_result(tmp_path, caplog):
    server = tool_server(tmp_path, BrokenAdapter(KeyError(f"{SECRET} {LOG_TEXT}")))

    with caplog.at_level(logging.DEBUG):
        result = call_through_protocol(server, arguments(elastic_query()))

    assert result.is_error is True
    logged = caplog.text + "".join(logged_tracebacks(caplog))
    for text in (SECRET, "UNION SELECT"):
        assert text not in error_text(result)
        assert text not in logged


@pytest.mark.parametrize(
    ("error_type", "fixed"),
    [
        (SiemUnavailableError, UNAVAILABLE_MESSAGE),
        (SiemAdapterError, ADAPTER_ERROR_MESSAGE),
    ],
)
def test_neutral_error_keeps_its_type_with_a_fixed_message(tmp_path, error_type, fixed):
    server = tool_server(tmp_path, BrokenAdapter(error_type("cannot reach the SIEM")))

    with pytest.raises(error_type) as raised:
        server.call("l1", QUERY_SIEM, **arguments(elastic_query()))
    assert str(raised.value) == fixed
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("error_type", [SiemUnavailableError, SiemAdapterError])
def test_neutral_error_message_from_adapter_is_replaced(tmp_path, error_type):
    """#111: secrets, log text or paths an adapter puts in a neutral error never leave the tool."""
    server = tool_server(tmp_path, BrokenAdapter(error_type(f"{SECRET} {LOG_TEXT} {PATH}")))

    with pytest.raises(error_type) as raised:
        server.call("l1", QUERY_SIEM, **arguments(elastic_query()))
    for text in (SECRET, LOG_TEXT, PATH):
        assert text not in str(raised.value)


@pytest.mark.parametrize("error_type", [SiemUnavailableError, SiemAdapterError])
def test_neutral_error_message_stays_out_of_the_mcp_result_and_log(tmp_path, caplog, error_type):
    """The SDK answers with a generic error but logs the traceback, so the log is checked too."""
    server = tool_server(tmp_path, BrokenAdapter(error_type(f"{SECRET} {LOG_TEXT} {PATH}")))

    with caplog.at_level(logging.DEBUG):
        result = call_through_protocol(server, arguments(elastic_query()))

    assert result.is_error is True
    logged = caplog.text + "".join(logged_tracebacks(caplog))
    for text in (SECRET, "UNION SELECT", PATH):
        assert text not in error_text(result)
        assert text not in logged


@pytest.mark.parametrize("record", not_c2_records())
def test_records_that_are_not_c2_become_an_adapter_error(tmp_path, record):
    """#111 [P2]: an answer that cannot become C2 is an answer that cannot be used."""
    server = tool_server(tmp_path, ReturningAdapter([record]))

    with pytest.raises(SiemAdapterError) as raised:
        server.call("l1", QUERY_SIEM, **arguments(elastic_query()))
    assert not isinstance(raised.value, ContractValidationError)
    assert str(raised.value) == ADAPTER_ERROR_MESSAGE
    assert raised.value.__cause__ is None
    for text in (SECRET, LOG_TEXT):
        assert text not in str(raised.value)


@pytest.mark.parametrize("record", not_c2_records())
def test_records_that_are_not_c2_stay_out_of_the_mcp_result_and_log(tmp_path, caplog, record):
    server = tool_server(tmp_path, ReturningAdapter([record]))

    with caplog.at_level(logging.DEBUG):
        result = call_through_protocol(server, arguments(elastic_query()))

    assert result.is_error is True
    logged = caplog.text + "".join(logged_tracebacks(caplog))
    assert "ContractValidationError" not in logged
    for text in (SECRET, "UNION SELECT"):
        assert text not in error_text(result)
        assert text not in logged


def test_invalid_query_is_still_a_value_error_before_the_adapter(tmp_path):
    adapter = FakeSiemMcp(BASE_URL, TOKEN)
    server = tool_server(tmp_path, adapter)
    sent = arguments(elastic_query()) | {"start_at": 2, "end_at": 1}

    with pytest.raises(ValueError):
        server.call("l1", QUERY_SIEM, **sent)
    assert adapter.queries == []


def test_empty_elasticsearch_still_answers_without_error(tmp_path):
    with FakeElasticsearch({ALERT_INDEX: [], EVENT_INDEX: []}) as server:
        adapter = create_elastic_mcp(
            siem_settings(server.url), ELASTIC_ENV, alias_tables=ALIAS_TABLES
        )
        assert adapter.query(elastic_query()) == ()
