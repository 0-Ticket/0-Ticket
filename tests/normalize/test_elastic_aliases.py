"""Box 4 alias tables for the elastic adapter (#99): ECS -> C3 and C13, dedup without dst_ip.

The C2 comes from the elastic connector's own hit conversion, so these check
what the pipeline will actually normalize.
"""

import copy
import json
from pathlib import Path

import pytest

from soc.branch.dedup import dedup_key
from soc.contracts import EventRecord, NormalizedAlert, validate_contract
from soc.ingest.connector import to_c2
from soc.ingest.siem.elastic import ALERT_SCENARIO, EVENT_SCENARIO, hit_to_c2
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer
from soc.normalize.runner import _alert_record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "elastic"
NOW = 1_800_000_000_000
ORIGINAL_TIME_AL1 = 1_792_544_465_000  # 2026-10-21T01:01:05Z
TIMESTAMP_AL1 = 1_792_544_530_120  # 2026-10-21T01:02:10.120Z


def hits(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def normalize(hit, kind):
    scenario = ALERT_SCENARIO if kind == "alert" else EVENT_SCENARIO
    c2 = to_c2(hit_to_c2(hit, kind, scenario))
    return c2, Normalizer(load_alias_tables(None), 16_384).normalize(c2, NOW)


class _NoLookup:
    def enrich(self, *args):
        return type("Found", (), {"src_asset": None, "dst_asset": None, "user_info": None})()


def alert_record(hit):
    c2, alert = normalize(hit, "alert")
    return _alert_record(alert, c2.source_record_id, _NoLookup())


def test_default_tables_include_the_elastic_scenarios():
    tables = load_alias_tables(None)
    assert tables[ALERT_SCENARIO].table.kind == "alert"
    assert tables[EVENT_SCENARIO].table.kind == "event"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_lab_alerts_normalize_to_c3(index):
    _, alert = normalize(hits("alert_hits.json")[index], "alert")
    assert isinstance(alert, NormalizedAlert)
    assert alert.rule_id == "a2a-web-attack-juice-shop"
    assert alert.rule_name == "Web Attack - Juice Shop"
    assert alert.severity_id == 4
    assert alert.dst_ip is None  # the lab has no destination IP; nothing is made up
    assert alert.host is None  # host.name is the collector, kept in unmapped
    assert alert.unmapped["host"] == {"name": "logstash"}
    assert alert.techniques == []
    assert alert.src_ip and alert.http_url and isinstance(alert.http_status, int)


def test_alert_fields_from_nested_and_dotted_keys():
    first, _, dotted = (normalize(hit, "alert")[1] for hit in hits("alert_hits.json"))
    assert (first.src_ip, first.http_status) == ("198.51.100.23", 500)
    assert first.http_url == "/rest/products/search?q=')) UNION SELECT * FROM Users--"
    assert (dotted.src_ip, dotted.http_url) == (
        "192.0.2.77",
        "/#/search?q=<script>alert(1)</script>",
    )


def test_alert_time_is_the_original_event_time_with_timestamp_as_fallback():
    hit = hits("alert_hits.json")[0]
    assert normalize(hit, "alert")[1].time == ORIGINAL_TIME_AL1
    without = copy.deepcopy(hit)
    del without["_source"]["kibana.alert.original_time"]
    assert normalize(without, "alert")[1].time == TIMESTAMP_AL1


@pytest.mark.parametrize(
    ("severity", "severity_id"), [("low", 2), ("medium", 3), ("high", 4), ("critical", 5)]
)
def test_kibana_severity_maps_to_severity_id(severity, severity_id):
    hit = copy.deepcopy(hits("alert_hits.json")[0])
    hit["_source"]["kibana.alert.severity"] = severity
    assert normalize(hit, "alert")[1].severity_id == severity_id


def test_lab_events_normalize_to_c13_with_integer_status():
    results = [normalize(hit, "event")[1] for hit in hits("event_hits.json")]
    assert all(isinstance(result, EventRecord) for result in results)
    assert [result.http_status for result in results] == [200, 500, 403, 200, 200]
    assert [result.src_ip for result in results] == [
        "192.0.2.50",
        "198.51.100.23",
        "198.51.100.23",
        "192.0.2.50",
        "192.0.2.77",
    ]
    assert {(r.class_uid, r.activity) for r in results} == {(4002, "http_request")}
    assert results[3].http_url == "/rest/products/1"
    assert results[0].unmapped["user_agent"] == {"original": "Mozilla/5.0"}


def test_elastic_alert_without_dst_ip_has_stable_dedup_key():
    first, second, other = (alert_record(hit) for hit in hits("alert_hits.json"))
    assert first.dst_ip is None
    key = dedup_key(first)
    assert key is not None
    # Same rule, same single entity {src_ip}: the same key, so the second is a duplicate.
    assert dedup_key(second) == key
    assert dedup_key(other) not in (None, key)
    validate_contract("AlertRecord", first.model_dump(mode="json"))
