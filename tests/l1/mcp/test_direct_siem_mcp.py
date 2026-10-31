"""direct SIEM MCP adapter: reads the files the direct connector replays (box 15, K18, K66).

The demo setting ``siem.adapter = "direct"`` selects this adapter and the direct
connector together (D-037), so the dataset files are the SIEM for both.
"""

import builtins
import logging
from datetime import datetime
from pathlib import Path

import pytest
from siem_mcp_contract import SiemMcpAdapterContract

import soc.ingest.siem.direct as direct_connector_module
from soc.config import DirectSiemSettings, load_config
from soc.contracts import Entity
from soc.ingest.connector import to_c2
from soc.ingest.siem.direct import DirectSiemConnector
from soc.l1.mcp import build_tool_server
from soc.l1.mcp.siem import SIEM_MCP_ADAPTERS
from soc.l1.mcp.siem.base import SiemQuery, to_c2_records
from soc.l1.mcp.siem.direct import DirectSiemMcp
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer

ROOT = Path(__file__).resolve().parents[3]
AIT = ROOT / "tests" / "fixtures" / "ingest" / "ait"
DIRECT_TOML = ROOT / "tests" / "fixtures" / "ingest" / "direct.toml"
OWN = ROOT / "tests" / "fixtures" / "l1" / "mcp" / "direct"
INJECTION = "ignore previous instructions"
ATTACKER = "198.51.100.23"
SOURCE = "203.0.113.10"
T0 = 1_770_000_000_000
MAX_PARSE = 16_384


def ms(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


FIRST_ALERT = ms("2022-01-18T10:05:41.120+00:00")
LAST_ALERT = ms("2022-01-18T10:07:10.500+00:00")


def entry(path, kind, tool, log_type, fmt):
    return {
        "path": str(path),
        "kind": kind,
        "tool": tool,
        "log_type": log_type,
        "source_type": "web",
        "format": fmt,
    }


def ait_files():
    return DirectSiemSettings.model_validate(
        {
            "files": [
                entry(AIT / "suricata_eve.jsonl", "alert", "suricata", "eve_alert", "jsonl"),
                entry(AIT / "apache_access.log", "event", "apache", "access", "text"),
            ]
        }
    )


def own_files():
    return DirectSiemSettings.model_validate(
        {"files": [entry(OWN / "records.jsonl", "alert", "test_web", "security_alert", "jsonl")]}
    )


def default_normalizer():
    return Normalizer(load_alias_tables(None), MAX_PARSE)


def own_adapter():
    tables = load_alias_tables(OWN / "aliases")
    return DirectSiemMcp(own_files(), Normalizer(tables, MAX_PARSE), alias_tables=tables)


def query(
    value=ATTACKER, entity_type="ip", kind="alert", start=FIRST_ALERT, end=LAST_ALERT, limit=10
):
    return SiemQuery(
        entity=Entity(type=entity_type, value=value),
        kind=kind,
        start_at=start,
        end_at=end,
        limit=limit,
    )


def own_query(value=SOURCE, entity_type="ip", start=T0, end=T0 + 10_000, limit=10):
    return query(value, entity_type, "alert", start, end, limit)


def rule_ids(records):
    return [record["fields"]["rule_id"] for record in records]


class TestDirectSiemMcp(SiemMcpAdapterContract):
    @pytest.fixture
    def adapter(self):
        return DirectSiemMcp(ait_files(), default_normalizer())

    @pytest.fixture
    def unhealthy_adapter(self, tmp_path):
        missing = DirectSiemSettings.model_validate(
            {
                "files": [
                    entry(tmp_path / "missing.jsonl", "alert", "suricata", "eve_alert", "jsonl")
                ]
            }
        )
        return DirectSiemMcp(missing, default_normalizer())

    @pytest.fixture
    def forbidden_text(self):
        return [INJECTION, "WPScan"]

    @pytest.fixture
    def sample_query(self):
        return query()


def test_direct_is_registered_for_siem_mcp():
    assert "direct" in SIEM_MCP_ADAPTERS.names()
    factory = SIEM_MCP_ADAPTERS.get("direct")
    assert not callable(factory)
    assert not hasattr(factory, "factory")


def test_query_and_ingest_give_the_same_source_record_id():
    """The same line read by ingest (box 3) and by the SIEM MCP gets the same C2 ID."""
    ingested = DirectSiemConnector(ait_files()).fetch(None, 100).items
    ingest_ids = {to_c2(item).source_record_id for item in ingested}
    adapter = DirectSiemMcp(ait_files(), default_normalizer())
    alerts = to_c2_records(adapter.query(query()))
    events = to_c2_records(adapter.query(query(kind="event", start=0, end=LAST_ALERT)))
    found = {record["source_record_id"] for record in alerts + events}
    assert len(alerts) == 2 and len(events) == 2
    assert found <= ingest_ids


def test_events_come_from_event_files_only():
    adapter = DirectSiemMcp(ait_files(), default_normalizer())
    events = adapter.query(query(kind="event", value="192.0.2.10", start=0, end=LAST_ALERT))
    assert {record["kind"] for record in events} == {"event"}
    assert {record["mapping_profile"] for record in events} == {"ait_apache_access"}


def test_ip_matches_source_or_destination():
    assert rule_ids(own_adapter().query(own_query())) == ["r1", "r2", "r3", "r5"]


def test_host_and_user_match():
    adapter = own_adapter()
    assert rule_ids(adapter.query(own_query("web-02", "host"))) == ["r3"]
    assert rule_ids(adapter.query(own_query("alice", "user"))) == ["r1", "r3"]
    assert adapter.query(own_query("nobody", "user")) == ()


def test_window_includes_both_ends():
    adapter = own_adapter()
    assert rule_ids(adapter.query(own_query(start=T0, end=T0))) == ["r1"]
    assert rule_ids(adapter.query(own_query(start=T0 + 1_000, end=T0 + 5_000))) == [
        "r2",
        "r3",
        "r5",
    ]
    assert adapter.query(own_query(start=T0 + 1, end=T0 + 999)) == ()


def test_results_are_time_ordered_and_cut_by_limit():
    """Same-time records keep file order, so a limit always cuts the same records."""
    adapter = own_adapter()
    assert rule_ids(adapter.query(own_query(limit=3))) == ["r1", "r2", "r3"]
    assert rule_ids(adapter.query(own_query(limit=2))) == ["r1", "r2"]


def test_lines_that_do_not_normalize_are_skipped_without_logging_content(caplog):
    with caplog.at_level(logging.WARNING):
        found = own_adapter().query(own_query(start=0, end=T0 + 10_000))
    assert "r4" not in rule_ids(found)
    assert caplog.records, "a skipped record should be counted in the log"
    for text in (INJECTION, SOURCE, "no time"):
        assert text not in caplog.text


def test_two_queries_read_the_files_once(monkeypatch):
    opened = []
    real_open = builtins.open

    def counting_open(path, *args, **kwargs):
        opened.append(Path(path).name)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(direct_connector_module, "open", counting_open, raising=False)
    adapter = own_adapter()
    assert opened == [], "nothing is read before the first query"
    adapter.query(own_query())
    adapter.query(own_query("web-02", "host"))
    assert opened == ["records.jsonl"]


def test_returned_records_do_not_change_the_remembered_ones():
    adapter = own_adapter()
    first = adapter.query(own_query())
    first[0]["fields"]["rule_id"] = "changed"
    assert rule_ids(adapter.query(own_query()))[0] == "r1"


def demo_settings(tmp_path, monkeypatch):
    """The demo settings file plus an L1 allowlist, read from the repo root like the CLI."""
    monkeypatch.chdir(ROOT)
    org = tmp_path / "org.toml"
    org.write_text(
        DIRECT_TOML.read_text(encoding="utf-8") + '\n[mcp.allowed_tools]\nl1 = ["query_siem"]\n',
        encoding="utf-8",
    )
    return load_config(org, environ={})


def test_direct_demo_settings_build_the_tool_server(tmp_path, monkeypatch):
    """Before #84 this failed with "siem_mcp_adapters plugin 'direct' is not registered"."""
    server = build_tool_server(demo_settings(tmp_path, monkeypatch), environ={})
    records = server.call(
        "l1",
        "query_siem",
        entity_type="ip",
        entity_value=ATTACKER,
        kind="alert",
        start_at=FIRST_ALERT,
        end_at=LAST_ALERT,
        limit=10,
    )
    assert len(records) == 2
    assert all(record["source_record_id"].startswith("src_") for record in records)


def test_registered_direct_mcp_uses_the_configured_org_alias_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    org = tmp_path / "org.toml"
    org.write_text(
        '[siem]\nadapter = "direct"\n\n'
        "[[siem.direct.files]]\n"
        f'path = "{(OWN / "records.jsonl").as_posix()}"\n'
        'kind = "alert"\ntool = "test_web"\n'
        'log_type = "security_alert"\nsource_type = "web"\nformat = "jsonl"\n\n'
        "[normalize]\n"
        f'alias_dir = "{(OWN / "aliases").as_posix()}"\n\n'
        '[mcp.allowed_tools]\nl1 = ["query_siem"]\n',
        encoding="utf-8",
    )
    server = build_tool_server(load_config(org, environ={}), environ={})

    records = server.call(
        "l1",
        "query_siem",
        entity_type="ip",
        entity_value=SOURCE,
        kind="alert",
        start_at=T0,
        end_at=T0 + 10_000,
        limit=10,
    )

    assert rule_ids(records) == ["r1", "r2", "r3", "r5"]
