"""원본(ELK hit)을 OCSF 알럿·이벤트로 바꾸는 변환과 OCSF 검사를 손으로 만든 샘플로 확인한다."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import validate_contract
from soc.ids import new_id
from soc.normalize.errors import NormalizeError
from soc.normalize.mapping import RawRow, Result, normalize
from soc.normalize.ocsf_schema import validate_ocsf

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "normalize" / "raw.json").read_text(encoding="utf-8")
)
SUCCESS = [case for case in CASES if "error" not in case["expect"]]
FAILURE = [case for case in CASES if "error" in case["expect"]]
NOV_4_0100 = int(datetime(2026, 11, 4, 1, 0, tzinfo=UTC).timestamp() * 1000)


def raw_row(case: dict[str, Any]) -> RawRow:
    """샘플 한 건으로 새 id를 가진 RawRow를 만든다. 원본은 복사해 쓴다.

    Args:
        case: raw.json의 샘플 한 건(kind, original을 가진다).
    """
    return RawRow(id=new_id("raw"), kind=case["kind"], original=copy.deepcopy(case["original"]))


def normalize_and_check(raw: RawRow) -> Result:
    """변환한 뒤 OCSF 검사와 계약 검증까지 통과시킨다.

    Args:
        raw: 변환할 원본.
    """
    result = normalize(raw)
    validate_ocsf(result.row["ocsf"])
    validate_contract(result.kind, result.row)
    return result


@pytest.mark.parametrize("case", SUCCESS, ids=lambda case: case["case"])
def test_samples_become_valid_results(case: dict[str, Any]) -> None:
    expect = case["expect"]

    result = normalize_and_check(raw_row(case))

    assert result.kind == expect["kind"]
    assert result.row["ocsf"]["class_uid"] == expect["class_uid"]
    assert result.row["ocsf"]["activity_id"] == expect["activity_id"]
    assert [
        [entity["type"], entity["value"], entity["role"]] for entity in result.row["entities"]
    ] == expect["entities"]
    assert result.row["assets"] == []
    for key in ("severity", "title", "rule_id", "summary"):
        if key in expect:
            assert result.row[key] == expect[key]


@pytest.mark.parametrize("case", FAILURE, ids=lambda case: case["case"])
def test_unusable_samples_fail_with_a_code(case: dict[str, Any]) -> None:
    with pytest.raises(NormalizeError) as raised:
        normalize_and_check(raw_row(case))

    assert raised.value.code == case["expect"]["error"]


def test_result_points_at_its_raw_record() -> None:
    raw = raw_row(SUCCESS[0])

    assert normalize(raw).row["raw_id"] == raw.id


def test_alert_time_prefers_the_original_event_time() -> None:
    by_case = {case["case"]: case for case in CASES}

    original = normalize(raw_row(by_case["alert_flat_keys"])).row["time"]
    fallback = normalize(raw_row(by_case["alert_without_rule_id_and_severity"])).row["time"]

    assert original == NOV_4_0100
    assert fallback == NOV_4_0100


def test_web_event_keeps_only_listed_http_methods() -> None:
    by_case = {case["case"]: case for case in CASES}

    listed = normalize(raw_row(by_case["web_nested_fields"])).row["ocsf"]
    unlisted = normalize(raw_row(by_case["web_unlisted_method"])).row["ocsf"]

    assert listed["http_request"]["http_method"] == "GET"
    assert "http_method" not in unlisted["http_request"]


def test_original_is_not_modified() -> None:
    for case in CASES:
        raw = raw_row(case)
        before = copy.deepcopy(raw.original)
        try:
            normalize(raw)
        except NormalizeError:
            pass
        assert raw.original == before


@pytest.fixture
def valid_ocsf() -> dict[str, Any]:
    return normalize(raw_row(SUCCESS[0])).row["ocsf"]


def test_ocsf_check_accepts_a_valid_object(valid_ocsf: dict[str, Any]) -> None:
    validate_ocsf(valid_ocsf)


@pytest.mark.parametrize(
    "change",
    [
        lambda ocsf: ocsf.pop("finding_info"),
        lambda ocsf: ocsf.update(unknown_attribute=1),
        lambda ocsf: ocsf.update(time="2026-11-04T01:00:00Z"),
        lambda ocsf: ocsf.update(severity_id=7),
        lambda ocsf: ocsf["metadata"].pop("version"),
        lambda ocsf: ocsf["finding_info"].pop("uid"),
        lambda ocsf: ocsf.update(time=True),
    ],
    ids=[
        "missing_required",
        "unknown_attribute",
        "wrong_type",
        "enum_value_out_of_range",
        "missing_required_inside_object",
        "missing_required_in_nested_object",
        "bool_is_not_integer",
    ],
)
def test_ocsf_check_rejects_a_broken_object(valid_ocsf: dict[str, Any], change: Any) -> None:
    change(valid_ocsf)

    with pytest.raises(NormalizeError) as raised:
        validate_ocsf(valid_ocsf)

    assert raised.value.code == "schema_failed"


@pytest.mark.parametrize("class_uid", [9999, "2004", None, True])
def test_ocsf_check_rejects_an_unknown_class(valid_ocsf: dict[str, Any], class_uid: object) -> None:
    valid_ocsf["class_uid"] = class_uid

    with pytest.raises(NormalizeError) as raised:
        validate_ocsf(valid_ocsf)

    assert raised.value.code == "schema_failed"
