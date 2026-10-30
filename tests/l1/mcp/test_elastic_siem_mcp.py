"""elastic SIEM MCP adapter (box 15, #99, K18, K66): queries a fake ES, never a real one.

``siem.adapter = "elastic"`` selects this adapter and the box 3 connector together
(D-037), so both read the same indices and give a document the same C2 ID.
"""

import json
import logging
from pathlib import Path
from urllib.parse import unquote

import pytest
from fake_elasticsearch import (
    ALERT_INDEX,
    API_KEY,
    EVENT_INDEX,
    FakeElasticsearch,
    load_hits,
    to_ms,
    unreachable_url,
)
from siem_mcp_contract import SiemMcpAdapterContract

from soc.config import load_config
from soc.contracts import Entity
from soc.ingest.connector import open_connector, to_c2
from soc.ingest.siem.elastic import MUTABLE_ALERT_FIELDS, create_elastic
from soc.l1.mcp import build_tool_server
from soc.l1.mcp.siem import SIEM_MCP_ADAPTERS
from soc.l1.mcp.siem.base import SiemQuery, to_c2_records
from soc.l1.mcp.siem.elastic import create_elastic_mcp

ROOT = Path(__file__).resolve().parents[3]
DEMO_ELK = ROOT / "config" / "demo-elk" / "settings.toml"
ENV = {"SIEM_TOKEN": API_KEY}
ATTACKER = "198.51.100.23"
LOG_TEXT = "UNION SELECT"
BIG = 10_000
# al-1 and al-2: source event at 01:01:05, alert written at 01:02:10. al-4 has no
# original_time; its @timestamp is 01:01:30. Events ev-2 and ev-3 are at 01:01:05.
WINDOW_START = to_ms("2026-10-21T01:01:00.000Z")
WINDOW_END = to_ms("2026-10-21T01:01:40.000Z")
DAY_END = to_ms("2026-10-22T00:00:00.000Z")


def siem_settings(base_url):
    siem = load_config(environ={}).siem
    return siem.model_copy(update={"adapter": "elastic", "base_url": base_url})


def lab_indices():
    return {
        ALERT_INDEX: [
            *load_hits("alert_hits.json"),
            *load_hits("alert_hits_no_original_time.json"),
        ],
        EVENT_INDEX: load_hits("event_hits.json"),
    }


def query(
    value=ATTACKER,
    entity_type="ip",
    kind="alert",
    start=WINDOW_START,
    end=WINDOW_END,
    limit=10,
):
    return SiemQuery(
        entity=Entity(type=entity_type, value=value),
        kind=kind,
        start_at=start,
        end_at=end,
        limit=limit,
    )


def doc_ids(records):
    return [record["raw_ids"][0].rsplit("_", 1)[1] for record in records]


def search_bodies(fake):
    return [request.body for request in fake.requests if request.method == "POST"]


@pytest.fixture
def fake():
    with FakeElasticsearch(lab_indices()) as server:
        yield server


@pytest.fixture
def mcp(fake):
    return create_elastic_mcp(siem_settings(fake.url), ENV)


class TestElasticSiemMcp(SiemMcpAdapterContract):
    @pytest.fixture
    def adapter(self, mcp):
        return mcp

    @pytest.fixture
    def unhealthy_adapter(self):
        return create_elastic_mcp(siem_settings(unreachable_url()), ENV)

    @pytest.fixture
    def forbidden_text(self):
        return [API_KEY, LOG_TEXT, ATTACKER]

    @pytest.fixture
    def sample_query(self):
        return query()


def test_registered_as_elastic_like_the_connector():
    """One siem.adapter name selects the connector and the SIEM MCP (D-037)."""
    assert "elastic" in SIEM_MCP_ADAPTERS.names()
    assert SIEM_MCP_ADAPTERS.get("elastic").factory is create_elastic_mcp


def test_query_and_ingest_give_the_same_source_record_id(fake, mcp):
    """The same document read at ingest (box 3) and through the SIEM MCP gets the same C2 ID."""
    ingested = create_elastic(siem_settings(fake.url), ENV).fetch(None, BIG).items
    ingest_ids = {to_c2(item).source_record_id for item in ingested}
    alerts = to_c2_records(mcp.query(query()))
    events = to_c2_records(mcp.query(query(kind="event")))
    assert doc_ids(alerts) == ["al-1", "al-2", "al-4"]
    assert doc_ids(events) == ["ev-2", "ev-3"]
    assert {record["source_record_id"] for record in alerts + events} <= ingest_ids


def test_alert_window_uses_original_time_not_creation_time(mcp):
    """al-1 and al-2 were written at 01:02:10 for events at 01:01:05: the event time counts."""
    source_window = query(
        start=to_ms("2026-10-21T01:01:00.000Z"), end=to_ms("2026-10-21T01:01:10.000Z")
    )
    assert doc_ids(mcp.query(source_window)) == ["al-1", "al-2"]
    creation_window = query(
        start=to_ms("2026-10-21T01:02:00.000Z"), end=to_ms("2026-10-21T01:02:20.000Z")
    )
    assert mcp.query(creation_window) == ()


def test_alert_without_original_time_uses_its_timestamp(mcp):
    window = query(start=to_ms("2026-10-21T01:01:20.000Z"), end=to_ms("2026-10-21T01:01:40.000Z"))
    assert doc_ids(mcp.query(window)) == ["al-4"]


def test_alerts_come_in_the_order_of_the_normalized_time(mcp):
    """al-4 was written before al-1 and al-2 but its time (01:01:30) is after theirs (01:01:05)."""
    assert doc_ids(mcp.query(query())) == ["al-1", "al-2", "al-4"]
    assert doc_ids(mcp.query(query(limit=2))) == ["al-1", "al-2"]


def test_window_includes_both_ends(mcp):
    exact = to_ms("2026-10-21T01:01:05.000Z")
    assert doc_ids(mcp.query(query(start=exact, end=exact))) == ["al-1", "al-2"]
    assert doc_ids(mcp.query(query(kind="event", start=exact, end=exact))) == ["ev-2", "ev-3"]


def test_events_use_the_event_index_and_timestamp(fake, mcp):
    events = mcp.query(query(kind="event", value="192.0.2.50", start=0, end=WINDOW_END))
    assert doc_ids(events) == ["ev-1"]
    assert {record["mapping_profile"] for record in events} == {"elastic_access_event"}
    request = fake.requests[-1]
    assert unquote(request.path) == f"/{EVENT_INDEX}/_search"
    assert request.body["sort"] == [{"@timestamp": {"order": "asc", "numeric_type": "date"}}]
    assert "_source" not in request.body
    assert "runtime_mappings" not in request.body


def test_alerts_use_the_alert_index_without_mutable_fields(fake, mcp):
    alerts = mcp.query(query())
    assert {record["mapping_profile"] for record in alerts} == {"elastic_security_alert"}
    request = fake.requests[-1]
    assert unquote(request.path) == f"/{ALERT_INDEX}/_search"
    assert request.body["_source"] == {"excludes": list(MUTABLE_ALERT_FIELDS)}
    for record in alerts:
        assert "workflow_status" not in record["fields"]["kibana"]["alert"]
        assert "status" not in record["fields"]["kibana"]["alert"]


def test_dotted_and_nested_documents_match_alike(mcp):
    assert doc_ids(mcp.query(query("192.0.2.77", start=0, end=DAY_END))) == ["al-3"]
    events = mcp.query(query("192.0.2.50", kind="event", start=0, end=DAY_END))
    assert doc_ids(events) == ["ev-1", "ev-4"]


def test_host_and_user_are_terms_on_their_ecs_fields(fake, mcp):
    hosts = mcp.query(query("logstash", "host", start=0, end=WINDOW_END))
    assert doc_ids(hosts) == ["al-1", "al-2", "al-4"]
    assert entity_clause(fake.requests[-1].body) == {"term": {"host.name": {"value": "logstash"}}}
    assert mcp.query(query("alice", "user", start=0, end=WINDOW_END)) == ()
    assert entity_clause(fake.requests[-1].body) == {"term": {"user.name": {"value": "alice"}}}


def test_unknown_entity_type_sends_no_request(fake, mcp):
    assert mcp.query(query("x", "file_hash")) == ()
    assert fake.requests == []


def test_only_search_and_health_requests_reach_elasticsearch(fake, mcp):
    mcp.query(query())
    mcp.query(query(kind="event"))
    mcp.query(query("logstash", "host"))
    mcp.query(query("alice", "user"))
    mcp.health_check()
    assert fake.requests
    for request in fake.requests:
        assert request.path.endswith("/_search")
        if request.method == "POST":
            assert request.query == {}
            assert request.body is not None
        else:
            assert (request.method, request.query) == ("GET", {"size": ["0"]})
    assert {request.authorization for request in fake.requests} == {f"ApiKey {API_KEY}"}


def entity_clause(body):
    """The entity part of a query body: the second filter, after the time window."""
    return body["query"]["bool"]["filter"][1]


@pytest.mark.parametrize(
    ("entity_type", "value", "field"),
    [
        ("ip", '198.51.100.23" OR *:* \\*', "source.address"),
        ("ip", "*", "source.address"),
        ("host", 'logstash" OR host.name:*', "host.name"),
        ("user", "*", "user.name"),
    ],
)
def test_entity_value_with_quotes_and_wildcards_stays_a_term_value(
    fake, mcp, entity_type, value, field
):
    assert mcp.query(query(value, entity_type, start=0, end=DAY_END)) == ()
    (body,) = search_bodies(fake)
    assert entity_clause(body) == {"term": {field: {"value": value}}}
    text = json.dumps(body)
    assert "query_string" not in text and "wildcard" not in text


@pytest.mark.parametrize("value", ["not-an-ip", "fe80::1%eth0", "logstash"])
def test_non_ip_value_does_not_query_destination_ip(fake, mcp, value):
    mcp.query(query(value))
    (body,) = search_bodies(fake)
    assert entity_clause(body) == {"term": {"source.address": {"value": value}}}
    assert "destination.ip" not in json.dumps(body)


@pytest.mark.parametrize("value", [ATTACKER, "2001:db8::1"])
def test_ip_value_matches_source_address_or_destination_ip(fake, mcp, value):
    mcp.query(query(value))
    (body,) = search_bodies(fake)
    assert entity_clause(body) == {
        "bool": {
            "should": [
                {"term": {"source.address": {"value": value}}},
                {"term": {"destination.ip": {"value": value}}},
            ],
            "minimum_should_match": 1,
        }
    }


def test_destination_ip_matches_too():
    hit = load_hits("event_hits.json")[0]
    hit["_source"]["destination"] = {"ip": "192.0.2.200"}
    with FakeElasticsearch({ALERT_INDEX: [], EVENT_INDEX: [hit]}) as server:
        mcp = create_elastic_mcp(siem_settings(server.url), ENV)
        assert doc_ids(mcp.query(query("192.0.2.200", kind="event", start=0, end=DAY_END))) == [
            "ev-1"
        ]


def test_server_returns_at_most_limit_hits(fake, mcp):
    assert len(mcp.query(query(limit=1))) == 1
    assert search_bodies(fake)[-1]["size"] == 1


def test_unusable_hits_are_skipped_and_only_counted(caplog):
    """bad_hits.json: one document gives source.address twice (192.0.2.90 and .91)."""
    hits = [*load_hits("bad_hits.json"), *load_hits("event_hits.json")]
    with FakeElasticsearch({ALERT_INDEX: [], EVENT_INDEX: hits}) as server:
        mcp = create_elastic_mcp(siem_settings(server.url), ENV)
        with caplog.at_level(logging.WARNING):
            records = mcp.query(query("192.0.2.90", kind="event", start=0, end=DAY_END))
    assert records == ()
    assert "Skipped 1 Elasticsearch hit(s)" in caplog.text
    assert "192.0.2" not in caplog.text


def test_demo_elk_settings_build_the_tool_server(fake, tmp_path, monkeypatch):
    """Before this PR the ELK demo settings had no SIEM MCP adapter to build query_siem."""
    monkeypatch.chdir(ROOT)
    org = tmp_path / "org.toml"
    text = DEMO_ELK.read_text(encoding="utf-8").replace("http://localhost:9200", fake.url)
    org.write_text(text, encoding="utf-8")
    server = build_tool_server(load_config(org, environ=ENV), environ=ENV)
    records = server.call(
        "l1",
        "query_siem",
        entity_type="ip",
        entity_value=ATTACKER,
        kind="alert",
        start_at=WINDOW_START,
        end_at=WINDOW_END,
        limit=10,
    )
    assert len(records) == 3
    assert all(record["source_record_id"].startswith("src_") for record in records)


def test_org_alias_selector_is_shared_by_ingest_and_mcp(fake, tmp_path, monkeypatch):
    """An org C20 override can select a source pair absent from the defaults."""
    monkeypatch.chdir(ROOT)
    alias_dir = tmp_path / "aliases"
    alias_dir.mkdir()
    alert_alias = (ROOT / "src/soc/normalize/aliases/elastic_security_alert.toml").read_text(
        encoding="utf-8"
    )
    alert_alias = alert_alias.replace('tool = "kibana_security"', 'tool = "org_endpoint"')
    alert_alias = alert_alias.replace('log_type = "security_alert"', 'log_type = "edr_alert"')
    (alias_dir / "elastic_security_alert.toml").write_text(alert_alias, encoding="utf-8")

    org = tmp_path / "org.toml"
    settings_text = DEMO_ELK.read_text(encoding="utf-8").replace("http://localhost:9200", fake.url)
    settings_text = settings_text.replace(
        'alert_tool = "kibana_security"', 'alert_tool = "org_endpoint"'
    )
    settings_text = settings_text.replace(
        'alert_log_type = "security_alert"', 'alert_log_type = "edr_alert"'
    )
    settings_text += f'\n[normalize]\nalias_dir = "{alias_dir}"\n'
    org.write_text(settings_text, encoding="utf-8")
    settings = load_config(org, environ=ENV)

    server = build_tool_server(settings, environ=ENV)
    ingested = open_connector(settings, ENV).fetch(None).items
    records = server.call(
        "l1",
        "query_siem",
        entity_type="ip",
        entity_value=ATTACKER,
        kind="alert",
        start_at=WINDOW_START,
        end_at=WINDOW_END,
        limit=10,
    )

    ingested_ids = {record.source_record_id for record in ingested}
    assert {record["mapping_profile"] for record in records} == {"elastic_security_alert"}
    assert {record["source_record_id"] for record in records} <= ingested_ids
