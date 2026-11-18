"""Alert 정규화 뼈대(#326)를 손으로 만든 샘플로 확인한다: 소스 판별, 공통 구성, 폴백, 마스킹.

원본은 tests/fixtures/normalize/alert_skeleton.json이다(정제한 샘플을 줄여 다시 쓴 것).
"""

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.normalize.errors import FALLBACK_REASONS, PARTIAL_REASONS, NormalizeError
from soc.normalize.mapping import RawRow, Result, fallback_alert, normalize
from soc.normalize.mask import mask_headers
from soc.normalize.ocsf_schema import validate_ocsf

CASES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "normalize" / "alert_skeleton.json").read_text(
        encoding="utf-8"
    )
)
FOUND = [case for case in CASES if case["expect"]["outcome"] != "fallback"]
FALLBACK = [case for case in CASES if case["expect"]["outcome"] == "fallback"]
SENSOR_ID = "26d0b29d0b9a"


def ms(text: str) -> int:
    """ISO 8601 문자열을 epoch 밀리초로 바꾼다."""
    return to_epoch_ms(datetime.fromisoformat(text))


def raw_row(case: dict[str, Any]) -> RawRow:
    """샘플 한 건으로 RawRow를 만든다. 원본은 복사해 쓴다."""
    fetched_at = ms(case["fetched_at"]) if "fetched_at" in case else None
    return RawRow(
        id=new_id("raw"),
        kind="alert",
        original=copy.deepcopy(case["original"]),
        fetched_at=fetched_at,
    )


def check(result: Result) -> Result:
    """OCSF 검사와 계약 검증을 통과시킨다."""
    validate_ocsf(result.row["ocsf"])
    validate_contract(result.kind, result.row)
    return result


def triples(row: dict[str, Any]) -> list[list[Any]]:
    """엔티티 목록을 [type, value, role] 목록으로 바꾼다."""
    return [[entity["type"], entity["value"], entity["role"]] for entity in row["entities"]]


def attack_ids(ocsf: dict[str, Any]) -> list[str]:
    """finding_info.attacks에서 기법 ID 목록을 읽는다(하위 기법이면 그 ID)."""
    attacks = ocsf["finding_info"].get("attacks", [])
    return [(a.get("sub_technique") or a["technique"])["uid"] for a in attacks]


def alert_with(source: dict[str, Any]) -> RawRow:
    """필수 값만 가진 알럿 원본에 source 값을 더해 RawRow를 만든다."""
    base = {
        "@timestamp": "2026-11-13T00:00:00.000Z",
        "event": {"module": "suricata"},
        "kibana.alert.uuid": "u-1",
        "kibana.alert.rule.name": "Rule",
    }
    return RawRow(
        id=new_id("raw"), kind="alert", original={"_id": "u-1", "_source": {**base, **source}}
    )


@pytest.mark.parametrize("case", FOUND, ids=lambda case: case["case"])
def test_samples_become_a_detection_finding(case: dict[str, Any]) -> None:
    expect = case["expect"]
    raw = raw_row(case)
    before = copy.deepcopy(raw.original)

    result = check(normalize(raw))
    row, ocsf = result.row, result.row["ocsf"]

    assert raw.original == before
    assert result.kind == "alert"
    assert (result.source, result.outcome, result.error_code) == (
        expect["source"],
        expect["outcome"],
        expect["error_code"],
    )
    assert list(result.missing_fields) == expect["missing_fields"]
    assert (ocsf["category_uid"], ocsf["class_uid"], ocsf["activity_id"], ocsf["type_uid"]) == (
        2,
        expect["class_uid"],
        1,
        200401,
    )
    assert (ocsf["is_alert"], ocsf["status_id"]) == (True, 1)
    assert ocsf["time"] == ocsf["finding_info"]["created_time"] == ms(expect["time"])
    assert ocsf["start_time"] == ocsf["end_time"] == ms(expect["start_time"])
    assert row["time"] == ocsf["start_time"]
    assert row["severity"] == ocsf["severity_id"] == expect["severity"]
    assert row["title"] == ocsf["finding_info"]["title"] == expect["title"]
    assert row["rule_id"] == expect["rule_id"]
    assert ocsf["message"] == expect["message"]
    if "desc" in expect:
        assert ocsf["finding_info"]["desc"] == expect["desc"]
    assert ocsf.get("risk_score") == expect.get("risk_score")
    assert attack_ids(ocsf) == expect["attacks"]
    assert triples(row) == expect["entities"]
    assert row["triage"] is None
    assert row["details"] == {}
    assert "unmapped" not in ocsf
    assert ocsf["metadata"]["version"] == "1.9.0"
    assert SENSOR_ID not in json.dumps([row["entities"], ocsf, row["details"]])


@pytest.mark.parametrize("case", FOUND, ids=lambda case: case["case"])
def test_finding_uid_prefers_the_alert_uuid_then_the_hit_id(case: dict[str, Any]) -> None:
    original = case["original"]
    expected = original["_source"].get("kibana.alert.uuid") or original["_id"]

    uid = normalize(raw_row(case)).row["ocsf"]["finding_info"]["uid"]

    assert uid == expected


def test_the_alert_uuid_wins_over_a_different_hit_id() -> None:
    raw = alert_with({"kibana.alert.uuid": "uuid-1"})

    assert normalize(raw).row["ocsf"]["finding_info"]["uid"] == "uuid-1"


def test_rule_uid_and_name_describe_the_analytic() -> None:
    row = normalize(alert_with({"kibana.alert.rule.rule_id": "r-1"})).row

    assert row["ocsf"]["finding_info"]["analytic"] == {"name": "Rule", "uid": "r-1", "type_id": 1}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("low", 2), ("medium", 3), ("high", 4), ("critical", 5), ("informational", 0), (None, 0)],
)
def test_severity_follows_the_table_and_is_zero_otherwise(value: str | None, expected: int) -> None:
    row = normalize(alert_with({"kibana.alert.severity": value})).row

    assert row["severity"] == expected


@pytest.mark.parametrize("case", FALLBACK, ids=lambda case: case["case"])
def test_unreadable_alerts_become_a_class_zero_fallback(case: dict[str, Any]) -> None:
    expect = case["expect"]

    result = check(normalize(raw_row(case)))
    row, ocsf = result.row, result.row["ocsf"]

    assert (result.source, result.outcome, result.error_code) == (
        "unknown",
        "fallback",
        expect["error_code"],
    )
    assert result.error_code in FALLBACK_REASONS
    assert [ocsf[k] for k in ("class_uid", "category_uid", "activity_id", "type_uid")] == [0] * 4
    assert (ocsf["severity_id"], row["severity"]) == (0, 0)
    assert ocsf["time"] == row["time"] == ms(expect["time"])
    assert row["title"] == ocsf["message"] == f"정규화 실패: {expect['error_code']}"
    assert (row["rule_id"], row["entities"], row["assets"], row["triage"]) == (None, [], [], None)
    assert row["details"] == {
        "fallback": {
            "reason": expect["error_code"],
            **({"time_from": expect["time_from"]} if expect["time_from"] else {}),
        }
    }
    assert "finding_info" not in ocsf


def test_a_fallback_can_be_built_for_a_mapping_that_failed_validation() -> None:
    case = FOUND[0]

    result = check(fallback_alert(raw_row(case), "validation_failed"))

    assert (result.outcome, result.error_code) == ("fallback", "validation_failed")
    assert result.row["details"] == {"fallback": {"reason": "validation_failed"}}


def test_a_fallback_without_any_readable_time_is_a_failure() -> None:
    raw = RawRow(id=new_id("raw"), kind="alert", original={"_source": {"@timestamp": "garbage"}})

    with pytest.raises(NormalizeError) as raised:
        normalize(raw)

    assert raised.value.code == "validation_failed"


def test_reason_lists_are_separate_from_failure_codes() -> None:
    assert PARTIAL_REASONS == ("unknown_source",)
    assert set(FALLBACK_REASONS) == {
        "invalid_source",
        "missing_uid",
        "missing_title",
        "bad_time",
        "validation_failed",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("198.51.100.1:8080", ["ip", "198.51.100.1"]),
        ("198.51.100.1", ["ip", "198.51.100.1"]),
        ("[2001:db8::1]:8443", ["ip", "2001:db8::1"]),
        ("[2001:db8::1]", ["ip", "2001:db8::1"]),
        ("2001:db8::1", ["ip", "2001:db8::1"]),
        ("www.example.com:8443", ["domain", "www.example.com"]),
        ("www.example.com", ["domain", "www.example.com"]),
        ("999.1.1.1", ["domain", "999.1.1.1"]),
    ],
)
def test_a_domain_candidate_is_an_ip_when_its_value_looks_like_one(
    value: str, expected: list[str]
) -> None:
    for field in ({"url.domain": value}, {"destination": {"domain": value}}):
        row = normalize(alert_with(field)).row

        assert triples(row) == [[*expected, "dst"]]


def test_the_same_type_value_and_role_is_kept_once() -> None:
    row = normalize(
        alert_with({"url.domain": "198.51.100.1:80", "destination.domain": "198.51.100.1"})
    ).row

    assert triples(row) == [["ip", "198.51.100.1", "dst"]]


def test_the_same_ip_as_source_and_destination_keeps_both_roles() -> None:
    row = normalize(alert_with({"source.ip": "198.51.100.7", "destination.ip": "198.51.100.7"})).row

    assert triples(row) == [["ip", "198.51.100.7", "src"], ["ip", "198.51.100.7", "dst"]]


def test_the_destination_ip_is_still_kept_as_alert_evidence() -> None:
    ocsf = normalize(alert_with({"destination.ip": "192.0.2.20"})).row["ocsf"]

    assert ocsf["evidences"] == [{"dst_endpoint": {"ip": "192.0.2.20"}}]


def test_observables_come_from_the_entities() -> None:
    ocsf = normalize(
        alert_with({"source.ip": "198.51.100.7", "user.name": "alice", "url.original": "/x"})
    ).row["ocsf"]

    assert [(o["type_id"], o["value"]) for o in ocsf["observables"]] == [
        (2, "198.51.100.7"),
        (4, "alice"),
        (6, "/x"),
    ]


def test_headers_in_copied_text_are_masked_in_the_result() -> None:
    description = "probe\nCookie: session=SYNTHETIC\nset-cookie: a=b\nAUTHORIZATION: Bearer SYNTH"
    row = normalize(alert_with({"kibana.alert.rule.description": description})).row

    text = json.dumps([row["ocsf"], row["details"]])
    for secret in ("SYNTHETIC", "a=b", "SYNTH"):
        assert secret not in text
    assert (
        row["ocsf"]["message"]
        == "probe\nCookie: [REDACTED]\nset-cookie: [REDACTED]\nAUTHORIZATION: [REDACTED]"
    )


def test_mask_hides_header_values_by_key_ignoring_case() -> None:
    value = {
        "headers": {"cookie": "a=1", "Set-Cookie": "b=2", "AUTHORIZATION": "Basic x", "Host": "h"},
        "list": [{"COOKIE": ["a", "b"]}, "plain"],
    }
    before = copy.deepcopy(value)

    masked = mask_headers(value)

    assert masked == {
        "headers": {
            "cookie": "[REDACTED]",
            "Set-Cookie": "[REDACTED]",
            "AUTHORIZATION": "[REDACTED]",
            "Host": "h",
        },
        "list": [{"COOKIE": "[REDACTED]"}, "plain"],
    }
    assert value == before


def test_mask_hides_name_value_lines_only_at_a_line_start() -> None:
    text = "GET /\r\nCookie: a=1\r\nX-Cookie: keep\nnote: Cookie: inline\n  Authorization:Basic x"

    assert mask_headers(text) == (
        "GET /\r\nCookie: [REDACTED]\r\nX-Cookie: keep\nnote: Cookie: inline\n"
        "  Authorization: [REDACTED]"
    )


def test_mask_leaves_other_values_alone() -> None:
    value = {"n": 1, "b": True, "x": None, "s": "cookies are tasty", "l": [1, "a"]}

    assert mask_headers(value) == value
