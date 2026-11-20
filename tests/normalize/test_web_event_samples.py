"""손으로 만든 nginx 접근 이벤트와 ModSecurity 감사 이벤트를 정규화한다."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from soc.ids import new_id
from soc.normalize.errors import NormalizeError
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.ocsf_schema import validate_ocsf

SAMPLES = Path(__file__).parent.parent / "fixtures" / "normalize" / "events"
ACTIVITY_TIME = int(datetime(2026, 11, 19, 15, 49, 58, tzinfo=UTC).timestamp() * 1000)
COLLECTION_TIME = int(datetime(2026, 11, 19, 15, 50, 1, tzinfo=UTC).timestamp() * 1000)


@pytest.fixture
def nginx() -> RawRow:
    return RawRow(
        id=new_id("raw"),
        kind="event",
        original=json.loads((SAMPLES / "nginx.json").read_text(encoding="utf-8")),
    )


@pytest.fixture
def modsecurity() -> RawRow:
    return RawRow(
        id=new_id("raw"),
        kind="event",
        original=json.loads((SAMPLES / "modsecurity.json").read_text(encoding="utf-8")),
    )


def test_nginx_filebeat_sample_maps_ecs_http_fields(nginx: RawRow) -> None:
    row = normalize(nginx).row
    ocsf = row["ocsf"]

    validate_ocsf(ocsf)
    assert row["ocsf_class"] == ocsf["class_uid"] == 4002
    assert row["time"] == ocsf["time"] == ACTIVITY_TIME
    assert row["summary"] == ocsf["message"] == "GET /catalog 200"
    assert ocsf["http_request"]["http_method"] == "GET"
    assert ocsf["http_request"]["url"] == {
        "path": "/catalog",
        "url_string": "/catalog?sort=asc",
        "hostname": "example.com",
        "scheme": "https",
        "query_string": "sort=asc",
    }
    assert "dst_endpoint" not in ocsf
    assert ocsf["http_request"]["user_agent"] == "ExampleBrowser/1.0"
    assert ocsf["http_request"]["version"] == "1.1"
    assert ocsf["http_response"] == {"code": 200, "length": 512, "body_length": 256}
    assert ocsf["src_endpoint"]["location"] == {
        "country": "US",
        "region": "US-CA",
        "city": "Example City",
        "continent": "North America",
        "coordinates": [-120.5, 35.25],
    }
    assert ocsf["src_endpoint"]["autonomous_system"] == {"number": 64496, "name": "Example Network"}
    assert {(e["type"], e["value"], e["role"]) for e in row["entities"]} == {
        ("ip", "192.0.2.19", "src"),
        ("user", "example-user", "actor"),
        ("domain", "example.com", "dst"),
        ("url", "/catalog?sort=asc", "dst"),
    }
    assert len(row["entities"]) == 4


def test_nginx_omits_missing_and_malformed_optional_fields(nginx: RawRow) -> None:
    source = nginx.original["_source"]
    source["source"].pop("geo")
    source["source"].pop("as")
    source["http"].pop("version")
    source["http"]["response"]["bytes"] = True

    ocsf = normalize(nginx).row["ocsf"]

    assert ocsf["http_response"] == {"code": 200, "body_length": 256}
    assert "location" not in ocsf["src_endpoint"]
    assert "autonomous_system" not in ocsf["src_endpoint"]
    assert "version" not in ocsf["http_request"]


@pytest.mark.parametrize("lowercase_response_headers", [False, True])
def test_modsecurity_filebeat_sample_maps_transaction_fields(
    modsecurity: RawRow, lowercase_response_headers: bool
) -> None:
    transaction = modsecurity.original["_source"]["transaction"]
    if lowercase_response_headers:
        headers = transaction["response"]["headers"]
        transaction["response"]["headers"] = {key.lower(): value for key, value in headers.items()}

    row = normalize(modsecurity).row
    ocsf = row["ocsf"]

    validate_ocsf(ocsf)
    assert row["ocsf_class"] == ocsf["class_uid"] == 4002
    assert row["time"] == ocsf["time"] == ACTIVITY_TIME
    assert ocsf["src_endpoint"] == {"ip": "192.0.2.19", "port": 43210}
    assert ocsf["dst_endpoint"]["ip"] == "198.51.100.20"
    assert ocsf["dst_endpoint"]["port"] == 443
    assert ocsf["http_request"]["http_method"] == "GET"
    assert ocsf["http_request"]["url"]["hostname"] == "example.com"
    assert ocsf["http_request"]["version"] == "1.1"
    assert ocsf["http_request"]["user_agent"] == "ExampleBrowser/1.0"
    assert ocsf["http_response"] == {"code": 200, "length": 512, "content_type": "text/html"}
    assert ocsf["metadata"]["correlation_uid"] == "synthetic-request-001"
    assert ocsf["metadata"]["original_time"] == "Thu Nov 19 15:49:58 2026"
    assert ocsf["metadata"]["version"]
    assert ocsf["metadata"]["product"]["name"] == "Elasticsearch"
    assert [(e["type"], e["value"], e["role"]) for e in row["entities"]] == [
        ("ip", "192.0.2.19", "src"),
        ("ip", "198.51.100.20", "dst"),
        ("domain", "example.com", "dst"),
    ]


def test_modsecurity_only_reads_allowed_audit_fields(modsecurity: RawRow) -> None:
    before = normalize(modsecurity).row["ocsf"]
    transaction = modsecurity.original["_source"]["transaction"]
    transaction["response"]["body"] = "synthetic response body"
    transaction["response"]["headers"]["X-Example"] = "synthetic response header"
    transaction["request"]["headers"]["X-Example"] = "synthetic request header"
    transaction["messages"] = [{"message": "synthetic rule match"}]
    transaction["is_interrupted"] = True

    assert normalize(modsecurity).row["ocsf"] == before


def test_modsecurity_uses_collection_time_when_activity_time_is_absent(modsecurity: RawRow) -> None:
    del modsecurity.original["_source"]["transaction"]["time_stamp"]

    ocsf = normalize(modsecurity).row["ocsf"]

    assert ocsf["time"] == COLLECTION_TIME
    assert "original_time" not in ocsf["metadata"]


@pytest.mark.parametrize("invalid_time", ["invalid", "", None])
def test_modsecurity_rejects_present_but_invalid_activity_time(
    modsecurity: RawRow, invalid_time: str | None
) -> None:
    modsecurity.original["_source"]["transaction"]["time_stamp"] = invalid_time

    with pytest.raises(NormalizeError) as raised:
        normalize(modsecurity)

    assert raised.value.code == "validation_failed"


def test_modsecurity_rejects_missing_activity_and_collection_times(modsecurity: RawRow) -> None:
    source = modsecurity.original["_source"]
    del source["transaction"]["time_stamp"]
    del source["@timestamp"]

    with pytest.raises(NormalizeError) as raised:
        normalize(modsecurity)

    assert raised.value.code == "validation_failed"


def test_web_class_still_requires_an_http_request_or_response(nginx: RawRow) -> None:
    source = nginx.original["_source"]
    for key in ("http", "url", "user_agent"):
        del source[key]

    with pytest.raises(NormalizeError) as raised:
        validate_ocsf(normalize(nginx).row["ocsf"])

    assert raised.value.code == "schema_failed"


def test_event_source_detection_has_priority_over_index(nginx: RawRow) -> None:
    nginx.original["_index"] = "logs-aws.cloudtrail-synthetic"

    assert normalize(nginx).row["ocsf_class"] == 4002


@pytest.mark.parametrize(
    ("index", "expected_class"),
    [(".ds-filebeat-synthetic-000001", 0), ("logs-apache.access-synthetic", 4002)],
)
def test_event_without_matching_source_falls_back_to_index(
    nginx: RawRow, index: str, expected_class: int
) -> None:
    nginx.original["_index"] = index
    nginx.original["_source"]["event"]["module"] = "synthetic-other"

    row = normalize(nginx).row

    assert row["ocsf_class"] == expected_class
    assert any(entity["type"] == "host" for entity in row["entities"]) == (expected_class == 0)


def test_web_ecs_destination_ip_is_preserved(nginx: RawRow) -> None:
    nginx.original["_source"]["destination"]["ip"] = "198.51.100.20"

    row = normalize(nginx).row

    assert row["ocsf"]["dst_endpoint"]["ip"] == "198.51.100.20"
    assert {"type": "ip", "value": "198.51.100.20", "role": "dst"} in row["entities"]


@pytest.mark.parametrize(("method", "activity_id"), [("post", 6), ("brew", 99)])
def test_modsecurity_method_overrides_conflicting_ecs_method(
    modsecurity: RawRow, method: str, activity_id: int
) -> None:
    source = modsecurity.original["_source"]
    source["http"] = {"request": {"method": "GET"}}
    source["transaction"]["request"]["method"] = method

    ocsf = normalize(modsecurity).row["ocsf"]

    validate_ocsf(ocsf)
    assert ocsf["activity_id"] == activity_id
    if activity_id == 99:
        assert ocsf["activity_name"] == "BREW"
        assert "http_method" not in ocsf["http_request"]
    else:
        assert ocsf["http_request"]["http_method"] == "POST"
        assert "activity_name" not in ocsf


def test_modsecurity_uses_valid_activity_time_even_if_collection_time_is_invalid(
    modsecurity: RawRow,
) -> None:
    modsecurity.original["_source"]["@timestamp"] = "invalid"

    assert normalize(modsecurity).row["ocsf"]["time"] == ACTIVITY_TIME
