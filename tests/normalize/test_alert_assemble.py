"""Alert JSON 조립(#339, D-066): OCSF 최상위 + details. DB 없이 샘플 전체로 왕복을 본다."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import ContractError, validate_contract
from soc.contracts.alert import (
    DETAILS_KEYS,
    alert_model_input,
    alert_severity,
    alert_time,
    alert_title,
    assemble_alert,
)
from soc.ids import new_id
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.ocsf_schema import validate_alert_ocsf

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize"
CASES = json.loads((FIXTURES / "alert_skeleton.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((FIXTURES / "alert_json_expected.json").read_text(encoding="utf-8"))
OCSF_2004 = set(
    json.loads(Path("src/soc/normalize/ocsf/classes/2004.json").read_text())["attributes"]
)
OCSF_0 = set(json.loads(Path("src/soc/normalize/ocsf/classes/0.json").read_text())["attributes"])


def rows() -> list[tuple[str, dict[str, Any]]]:
    """normalize가 만든 alerts 행(이전 계약 모양). 정규화 못 하는 샘플은 뺀다."""
    out = []
    for case in CASES:
        raw = RawRow(
            id=new_id("raw"),
            kind="alert",
            original=copy.deepcopy(case["original"]),
            fetched_at=1_793_000_000_000 if "fetched_at" in case else None,
        )
        try:
            out.append((case["case"], normalize(raw).row))
        except Exception:  # fetched_at 없는 폴백 실패 샘플은 대상이 아니다
            continue
    return out


ROWS = rows()


def test_samples_include_2004_and_fallback() -> None:
    assert len(ROWS) >= 17
    assert {row["ocsf"]["class_uid"] for _, row in ROWS} == {2004, 0}


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_assembled_alert_is_ocsf_top_level_with_our_values_in_details(
    name: str, row: dict[str, Any]
) -> None:
    alert = assemble_alert(row)

    assert "ocsf" not in alert
    assert {k: v for k, v in alert.items() if k != "details"} == row["ocsf"]
    assert alert["details"] == {
        **row["details"],
        **{key: row[key] for key in DETAILS_KEYS},
    }
    validate_contract("alert", alert)
    validate_alert_ocsf(alert)


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_model_input_round_trips_to_the_previous_shape(name: str, row: dict[str, Any]) -> None:
    assert alert_model_input(assemble_alert(row)) == row


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_helpers_read_start_time_and_severity_like_the_columns(
    name: str, row: dict[str, Any]
) -> None:
    alert = assemble_alert(row)

    assert alert_time(alert) == row["time"]
    assert alert_severity(alert) == row["severity"]
    assert alert_title(alert) == row["title"]
    assert alert["time"] == row["ocsf"]["time"]  # 최상위 time은 OCSF 생성 시각이다


def test_only_time_and_severity_collide_with_ocsf_names() -> None:
    ours = {"id", "raw_id", "time", "severity", "title", "rule_id", "entities", "assets", "triage"}
    ours |= {"details"}  # 이전 Alert 계약의 10개 필드
    assert ours & OCSF_2004 == {"time", "severity"}
    assert ours & OCSF_0 == {"time", "severity"}


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_details_has_no_ocsf_attribute_names(name: str, row: dict[str, Any]) -> None:
    details = assemble_alert(row)["details"]
    assert not set(details) & (OCSF_2004 | OCSF_0)


def test_hand_written_expected_alert_json() -> None:
    for item in EXPECTED:
        alert = assemble_alert(item["row"])
        assert alert == item["alert"], item["name"]
        validate_contract("alert", alert)
        assert alert_time(alert) == item["alert_time"]
        assert alert_severity(alert) == item["alert_severity"]
        assert alert_title(alert) == item["alert_title"]


def test_assemble_rejects_details_key_collision() -> None:
    row = copy.deepcopy(ROWS[0][1])
    row["details"]["entities"] = []
    with pytest.raises(ValueError, match="details"):
        assemble_alert(row)


def test_assemble_rejects_ocsf_with_details_key() -> None:
    row = copy.deepcopy(ROWS[0][1])
    row["ocsf"]["details"] = {}
    with pytest.raises(ValueError, match="details"):
        assemble_alert(row)


def test_assemble_does_not_change_the_row() -> None:
    row = copy.deepcopy(ROWS[0][1])
    before = copy.deepcopy(row)
    assemble_alert(row)
    assert row == before


def test_severity_99_folds_to_zero() -> None:
    assert alert_severity({"severity_id": 99}) == 0
    assert alert_severity({"severity_id": 4}) == 4
    assert alert_severity({}) == 0


def test_time_prefers_start_time_and_falls_back_to_time() -> None:
    assert alert_time({"time": 5, "start_time": 3}) == 3
    assert alert_time({"time": 5}) == 5


def test_title_falls_back_to_message() -> None:
    assert alert_title({"finding_info": {"title": "x"}, "message": "m"}) == "x"
    assert alert_title({"message": "m"}) == "m"


def test_contract_requires_finding_info_only_for_2004() -> None:
    alert = assemble_alert(next(r for n, r in ROWS if r["ocsf"]["class_uid"] == 2004))
    del alert["finding_info"]
    with pytest.raises(ContractError):
        validate_contract("alert", alert)
    fallback = assemble_alert(next(r for n, r in ROWS if r["ocsf"]["class_uid"] == 0))
    assert "finding_info" not in fallback
    validate_contract("alert", fallback)


def test_contract_rule_id_is_required_but_nullable() -> None:
    alert = assemble_alert(next(r for n, r in ROWS if r["ocsf"]["class_uid"] == 0))
    assert alert["details"]["rule_id"] is None
    validate_contract("alert", alert)
    del alert["details"]["rule_id"]
    with pytest.raises(ContractError):
        validate_contract("alert", alert)


@pytest.mark.parametrize("key", DETAILS_KEYS)
def test_contract_requires_each_details_key(key: str) -> None:
    alert = assemble_alert(ROWS[0][1])
    del alert["details"][key]
    with pytest.raises(ContractError):
        validate_contract("alert", alert)
