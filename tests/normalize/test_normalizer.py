"""Box 4 normalization: C2 -> C3 / C13 / C12 by alias tables only (K4, K5, K34)."""

import json

import pytest
from normalize_fixtures import (
    NORMALIZE,
    NOW,
    dump,
    fake_waf_c2,
    load_ait_c2,
    make_c2,
    read_json,
)

from soc.contracts import EventRecord, NormalizedAlert, NormalizeFailure, validate_contract
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer

MAX_PARSE = 16_384


@pytest.fixture
def normalizer():
    return Normalizer(load_alias_tables(None), MAX_PARSE)


@pytest.fixture
def with_fake_scenario():
    return Normalizer(load_alias_tables(NORMALIZE / "aliases"), MAX_PARSE)


def test_ait_alerts_normalize_to_expected_c3(normalizer):
    expected = {
        row["source_record_id"]: row["c3"] for row in read_json(NORMALIZE / "expected_c3.json")
    }
    alerts = [item for item in load_ait_c2() if item.kind == "alert"]
    assert {item.source_record_id for item in alerts} == set(expected)
    for item in alerts:
        result = normalizer.normalize(item, NOW)
        assert isinstance(result, NormalizedAlert)
        assert dump(result) == expected[item.source_record_id]


def test_ait_events_normalize_to_expected_c13(normalizer):
    expected = read_json(NORMALIZE / "expected_c13.json")
    events = [item for item in load_ait_c2() if item.kind == "event"]
    results = [normalizer.normalize(item, NOW) for item in events]
    assert all(isinstance(result, EventRecord) for result in results)
    assert [dump(result) for result in results] == expected


def test_wazuh_alerts_normalize_to_expected_c3(normalizer):
    """#79, #113: AIT-ADS Wazuh alerts. dst_ip falls back to agent.ip. data.id is the response
    code in access logs; an Apache error code (AH01630) or a fast.log ID (gid:sid:rev) leaves
    http_status null and stays in unmapped instead of failing."""
    items = read_json(NORMALIZE / "wazuh_c2.json")
    expected = read_json(NORMALIZE / "wazuh_expected_c3.json")
    results = [
        normalizer.normalize(make_c2(i["kind"], i["scenario"], i["fields"], i["raw_ids"]), NOW)
        for i in items
    ]
    assert all(isinstance(result, NormalizedAlert) for result in results)
    assert [dump(result) for result in results] == expected


@pytest.mark.parametrize(
    ("level", "severity_id"), [(0, 1), (5, 2), (7, 3), (10, 3), (12, 4), (15, 5)]
)
def test_wazuh_rule_level_maps_to_severity_id(normalizer, level, severity_id):
    fields = {
        "@timestamp": "2022-01-18T10:00:00.000000Z",
        "agent": {"ip": "192.0.2.80"},
        "rule": {"id": "31101", "level": level, "description": "Web server 400 error code."},
        "data": {"srcip": "198.51.100.23"},
    }
    result = normalizer.normalize(make_c2("alert", "ait_wazuh_alert", fields), NOW)
    assert result.severity_id == severity_id


def test_injected_text_stays_data_in_unmapped(normalizer):
    event = [item for item in load_ait_c2() if item.kind == "event"][-1]
    result = normalizer.normalize(event, NOW)
    assert result.unmapped["message"]["user_agent"].startswith("ignore previous instructions")
    assert result.activity == "http_request"


def test_fake_scenario_normalizes_by_alias_table_only(with_fake_scenario):
    result = with_fake_scenario.normalize(fake_waf_c2(), NOW)
    assert isinstance(result, NormalizedAlert)
    assert dump(result) == read_json(NORMALIZE / "fake_waf_expected_c3.json")


def test_different_field_names_land_in_the_same_c3_fields(with_fake_scenario):
    ait = with_fake_scenario.normalize(load_ait_c2()[0], NOW)
    waf = with_fake_scenario.normalize(fake_waf_c2(), NOW)
    for field in ("time", "severity_id", "rule_id", "rule_name", "src_ip", "dst_ip", "dst_port"):
        assert getattr(ait, field) is not None
        assert getattr(waf, field) is not None


def test_unmapped_keeps_unused_fields_nested(with_fake_scenario):
    item = fake_waf_c2()
    fields = {**item.fields, "client": {**item.fields["client"], "geo": {"country": "XX"}}}
    result = with_fake_scenario.normalize(make_c2("alert", "fake_waf_alert", fields), NOW)
    assert result.unmapped == {"account": "", "client": {"geo": {"country": "XX"}}}


def test_extensions_map_moves_values_to_extensions(with_fake_scenario):
    result = with_fake_scenario.normalize(fake_waf_c2(), NOW)
    assert result.extensions == {"acme.tenant": "acme-01"}
    assert "tenant" not in result.unmapped


def test_source_techniques_beat_default(with_fake_scenario):
    fields = {**fake_waf_c2().fields, "threat": {"technique": "T1059"}}
    result = with_fake_scenario.normalize(make_c2("alert", "fake_waf_alert", fields), NOW)
    assert result.techniques == ["T1059"]


@pytest.mark.parametrize(
    ("time_format", "value", "expected"),
    [
        ("iso8601", "2022-01-18T10:05:41.120000+0000", 1642500341120),
        ("iso8601", "2022-01-18T10:05:41Z", 1642500341000),
        ("epoch_s", 1642500341, 1642500341000),
        ("epoch_s", "1642500341.12", 1642500341120),
        ("epoch_ms", 1642500341120, 1642500341120),
        ("epoch_ms", "1642500341120", 1642500341120),
        ("%d/%b/%Y:%H:%M:%S %z", "18/Jan/2022:10:05:41 +0900", 1642467941000),
    ],
)
def test_time_formats_convert_to_epoch_ms(tmp_path, time_format, value, expected):
    normalizer = Normalizer(load_alias_tables(_table_dir(tmp_path, time_format)), MAX_PARSE)
    result = normalizer.normalize(make_c2("alert", "time_case", _time_case(value)), NOW)
    assert isinstance(result, NormalizedAlert)
    assert result.time == expected


@pytest.mark.parametrize(
    ("time_format", "value"),
    [
        ("iso8601", "2022-01-18T10:05:41"),
        ("epoch_ms", "12.5"),
        ("epoch_s", True),
        ("%d/%b/%Y:%H:%M:%S", "18/Jan/2022:10:05:41"),
    ],
)
def test_time_without_zone_or_wrong_type_is_bad_value(tmp_path, time_format, value):
    normalizer = Normalizer(load_alias_tables(_table_dir(tmp_path, time_format)), MAX_PARSE)
    result = normalizer.normalize(make_c2("alert", "time_case", _time_case(value)), NOW)
    assert isinstance(result, NormalizeFailure)
    assert result.reason == "bad_value"


def test_severity_map_converts_source_value(normalizer):
    for severity, expected in (("1", 4), (2, 3), (3, 2)):
        fields = {
            **load_ait_c2()[0].fields,
            "alert": {**load_ait_c2()[0].fields["alert"], "severity": severity},
        }
        result = normalizer.normalize(make_c2("alert", "ait_suricata_alert", fields), NOW)
        assert result.severity_id == expected


@pytest.mark.parametrize(
    "case", read_json(NORMALIZE / "failures_c2.json"), ids=lambda case: case["case"]
)
def test_failures_become_c12(normalizer, case):
    item = make_c2(case["kind"], case["scenario"], case["fields"])
    result = normalizer.normalize(item, NOW)
    assert isinstance(result, NormalizeFailure)
    assert result.reason == case["reason"]
    assert result.missing_fields == case["missing_fields"]
    assert result.scenario == case["scenario"]
    assert result.raw_ids == item.raw_ids
    assert result.failed_at == NOW
    assert result.detail


@pytest.mark.parametrize(
    "case", read_json(NORMALIZE / "failures_c2.json"), ids=lambda case: case["case"]
)
def test_failure_detail_has_no_raw_text(normalizer, case):
    result = normalizer.normalize(make_c2(case["kind"], case["scenario"], case["fields"]), NOW)
    text = json.dumps(dump(result))
    assert "secretmarker" not in text
    assert "198.51.100.23" not in text


@pytest.mark.parametrize(
    "case", read_json(NORMALIZE / "optional_number_c2.json"), ids=lambda case: case["case"]
)
def test_optional_number_that_does_not_convert_is_null(normalizer, case):
    """#113: the field is null (never 0), the record still normalizes and the value stays in
    unmapped."""
    result = normalizer.normalize(make_c2(case["kind"], case["scenario"], case["fields"]), NOW)
    contract = "NormalizedAlert" if case["kind"] == "alert" else "EventRecord"
    assert isinstance(result, NormalizedAlert if case["kind"] == "alert" else EventRecord)
    output = dump(validate_contract(contract, dump(result)))
    assert {name: output[name] for name in case["expected"]} == case["expected"]
    assert output["unmapped"] == case["unmapped"]
    assert output["src_ip"] == "198.51.100.23"


def test_nulled_number_stays_out_of_unmapped_when_its_field_is_used_elsewhere(tmp_path):
    directory = _table_dir(tmp_path, "epoch_ms")
    table = directory / "time_case.toml"
    text = table.read_text(encoding="utf-8")
    text = text.replace("[severity_map]", '[extensions_map]\n"p" = "acme.port"\n[severity_map]')
    table.write_text(text + '\nsrc_port = ["p"]\n', encoding="utf-8")
    normalizer = Normalizer(load_alias_tables(directory), MAX_PARSE)
    fields = {**_time_case(1642500341120), "p": "web-01"}
    result = normalizer.normalize(make_c2("alert", "time_case", fields), NOW)
    assert result.src_port is None
    assert result.extensions == {"acme.port": "web-01"}
    assert result.unmapped == {}


def test_line_longer_than_parse_limit_is_bad_value_without_running_the_pattern():
    normalizer = Normalizer(load_alias_tables(None), 100)
    line = "198.51.100.23 - - " + "A" * 200
    result = normalizer.normalize(make_c2("event", "ait_apache_access", {"message": line}), NOW)
    assert isinstance(result, NormalizeFailure)
    assert result.reason == "bad_value"
    assert "message" in result.detail
    assert "AAAA" not in result.detail


def test_line_at_parse_limit_is_parsed():
    event = [item for item in load_ait_c2() if item.kind == "event"][0]
    normalizer = Normalizer(load_alias_tables(None), len(event.fields["message"]))
    assert isinstance(normalizer.normalize(event, NOW), EventRecord)


def test_hostile_line_does_not_hang_the_default_pattern(normalizer):
    line = '198.51.100.23 - - [18/Jan/2022:10:05:41 +0000] "GET ' + "/a" * 5000 + " " * 5000 + '"'
    result = normalizer.normalize(make_c2("event", "ait_apache_access", {"message": line}), NOW)
    assert isinstance(result, NormalizeFailure)


def test_message_that_is_not_text_is_missing(normalizer):
    result = normalizer.normalize(make_c2("event", "ait_apache_access", {"message": {"a": 1}}), NOW)
    assert isinstance(result, NormalizeFailure)
    assert result.reason == "missing_required"


def _time_case(value):
    return {"t": value, "ip": "198.51.100.23", "r": "rule-1", "sev": "high"}


def _table_dir(tmp_path, time_format):
    directory = tmp_path / "aliases"
    directory.mkdir(exist_ok=True)
    (directory / "time_case.toml").write_text(
        "\n".join(
            [
                'scenario = "time_case"',
                'kind = "alert"',
                "class_uid = 2004",
                f"time_format = {json.dumps(time_format)}",
                "[severity_map]",
                "high = 4",
                "[fields]",
                'time = ["t"]',
                'severity_id = ["sev"]',
                'rule_id = ["r"]',
                'rule_name = ["r"]',
                'src_ip = ["ip"]',
            ]
        ),
        encoding="utf-8",
    )
    return directory
