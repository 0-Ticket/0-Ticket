"""Alert -> entity list (boxes 25, 11): fixed order, no empty values, no repeats."""

import json
from pathlib import Path

import pytest

from soc.contracts import validate_contract
from soc.l1.entities import alert_entities

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def alert(**fields):
    base = json.loads((FIXTURES / "tickets" / "alert_record_src_asset.json").read_text())
    return validate_contract("AlertRecord", base | fields)


def test_fields_map_to_entities_in_the_fixed_order():
    record = alert(src_ip="203.0.113.10", dst_ip="198.51.100.20", host="web-01", user="alice")
    assert alert_entities(record) == [
        {"type": "ip", "value": "203.0.113.10"},
        {"type": "ip", "value": "198.51.100.20"},
        {"type": "host", "value": "web-01"},
        {"type": "user", "value": "alice"},
    ]


def test_stored_sample_alert_gives_ip_ip_host():
    data = json.loads((FIXTURES / "store" / "alert_records.json").read_text())[0]
    assert alert_entities(validate_contract("AlertRecord", data)) == [
        {"type": "ip", "value": "198.51.100.23"},
        {"type": "ip", "value": "192.0.2.80"},
        {"type": "host", "value": "web-01"},
    ]


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_values_are_left_out(empty):
    record = alert(src_ip="203.0.113.10", dst_ip=empty, host=empty, user=empty)
    assert alert_entities(record) == [{"type": "ip", "value": "203.0.113.10"}]


def test_same_entity_is_listed_once_at_its_first_place():
    record = alert(src_ip=None, dst_ip="192.0.2.80", host="192.0.2.80", user=None)
    assert alert_entities(record) == [
        {"type": "ip", "value": "192.0.2.80"},
        {"type": "host", "value": "192.0.2.80"},
    ]
    same_ip = alert(src_ip="192.0.2.80", dst_ip="192.0.2.80", host=None, user=None)
    assert alert_entities(same_ip) == [{"type": "ip", "value": "192.0.2.80"}]


def test_values_are_kept_as_they_are():
    record = alert(host=" web-01 ", user="<b>x</b>")
    assert {"type": "host", "value": " web-01 "} in alert_entities(record)
    assert {"type": "user", "value": "<b>x</b>"} in alert_entities(record)
