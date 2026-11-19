"""Event JSON 조립(#347, D-068): OCSF 최상위 + details. DB 없이 raw.json의 이벤트 샘플로 본다."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import ContractError, validate_contract
from soc.contracts.event import (
    DETAILS_KEYS,
    assemble_event,
    event_class,
    event_model_input,
    event_summary,
    event_time,
)
from soc.ids import new_id
from soc.normalize.mapping import RawRow, derive_event_columns, normalize
from soc.normalize.ocsf_schema import validate_event_ocsf

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize"
CASES = json.loads((FIXTURES / "raw.json").read_text(encoding="utf-8"))
EVENT_CASES = [c for c in CASES if c["kind"] == "event" and "error" not in c["expect"]]


def raw_row(case: dict[str, Any], **source: Any) -> RawRow:
    original = copy.deepcopy(case["original"])
    original["_source"].update(source)
    return RawRow(id=new_id("raw"), kind="event", original=original)


def rows() -> list[tuple[str, dict[str, Any]]]:
    return [(c["case"], normalize(raw_row(c)).row) for c in EVENT_CASES]


ROWS = rows()


def base_case() -> dict[str, Any]:
    return next(c for c in CASES if c["case"] == "event_without_supported_class")


def test_samples_include_the_three_current_classes() -> None:
    assert {row["ocsf"]["class_uid"] for _, row in ROWS} == {0, 4002, 6003}


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_assembled_event_is_ocsf_top_level_with_our_values_in_details(
    name: str, row: dict[str, Any]
) -> None:
    event = assemble_event(row)

    assert "ocsf" not in event
    assert {k: v for k, v in event.items() if k != "details"} == row["ocsf"]
    assert event["details"] == {**row["details"], **{key: row[key] for key in DETAILS_KEYS}}
    validate_contract("event", event)
    validate_event_ocsf(event)


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_model_input_round_trips_to_the_row_shape(name: str, row: dict[str, Any]) -> None:
    assert event_model_input(assemble_event(row)) == row


@pytest.mark.parametrize(("name", "row"), ROWS, ids=[n for n, _ in ROWS])
def test_columns_are_derived_from_ocsf_only(name: str, row: dict[str, Any]) -> None:
    assert derive_event_columns(row["ocsf"]) == {
        "time": row["time"],
        "ocsf_class": row["ocsf"]["class_uid"],
        "summary": row["summary"],
    }
    event = assemble_event(row)
    assert (event_time(event), event_class(event), event_summary(event)) == (
        row["time"],
        row["ocsf_class"],
        row["summary"],
    )


def test_event_time_prefers_start_time_like_alerts() -> None:
    assert event_time({"time": 5}) == 5
    assert event_time({"time": 5, "start_time": 3}) == 3


def test_summary_falls_back_to_event_when_message_is_missing() -> None:
    assert event_summary({"message": "GET / 200"}) == "GET / 200"
    assert event_summary({}) == "event"


def test_details_must_not_repeat_our_keys_or_ocsf_names() -> None:
    row = dict(ROWS[0][1])
    with pytest.raises(ValueError):
        assemble_event({**row, "details": {"id": "x"}})
    with pytest.raises(ValueError):
        assemble_event({**row, "ocsf": {**row["ocsf"], "details": {}}})


def test_details_with_an_ocsf_attribute_name_is_not_added_by_normalization() -> None:
    for _, row in ROWS:
        assert set(row["details"]) & set(row["ocsf"]) == set()


def test_contract_requires_the_four_top_level_keys_and_details_keys() -> None:
    event = assemble_event(ROWS[0][1])
    for key in ("class_uid", "time", "severity_id", "details"):
        broken = {k: v for k, v in event.items() if k != key}
        with pytest.raises(ContractError):
            validate_contract("event", broken)
    for key in DETAILS_KEYS:
        broken = {**event, "details": {k: v for k, v in event["details"].items() if k != key}}
        with pytest.raises(ContractError):
            validate_contract("event", broken)


def test_contract_rejects_a_class_that_is_not_stored() -> None:
    event = {**assemble_event(ROWS[0][1]), "class_uid": 1007}
    with pytest.raises(ContractError):
        validate_contract("event", event)


# activity_id = 99 이면 activity_name에 출처 고유 값이 있어야 한다(OCSF 규칙, D-068)
def test_unlisted_http_method_is_kept_in_activity_name() -> None:
    case = next(c for c in CASES if c["case"] == "web_unlisted_method")
    ocsf = normalize(raw_row(case)).row["ocsf"]

    assert ocsf["activity_id"] == 99
    assert ocsf["activity_name"] == "BREW"
    assert ocsf["type_uid"] == 4002 * 100 + 99


def test_unlisted_api_operation_is_kept_in_activity_name() -> None:
    case = next(c for c in CASES if c["case"] == "cloud_unlisted_verb")
    ocsf = normalize(raw_row(case)).row["ocsf"]

    assert ocsf["activity_id"] == 99
    assert ocsf["activity_name"] == "Microsoft.Compute/virtualMachines/write"


def test_listed_methods_and_operations_have_no_activity_name() -> None:
    for name in ("web_nested_fields", "cloud_read_call"):
        case = next(c for c in CASES if c["case"] == name)
        assert "activity_name" not in normalize(raw_row(case)).row["ocsf"]


def test_base_event_with_an_action_uses_activity_id_99_and_activity_name() -> None:
    row = normalize(raw_row(base_case())).row

    assert row["ocsf"]["class_uid"] == 0
    assert row["ocsf"]["activity_id"] == 99
    assert row["ocsf"]["activity_name"] == "logon"
    assert row["ocsf"]["type_uid"] == 99
    assert row["ocsf"]["message"] == row["summary"] == "logon"


def test_base_event_without_an_action_uses_the_dataset_then_event() -> None:
    case = base_case()
    for source, expected in (
        ({"event": {"dataset": "system.auth"}}, "system.auth"),
        ({"event": {}}, "event"),
    ):
        row = normalize(raw_row(case, **source)).row
        assert row["ocsf"]["activity_id"] == 0
        assert "activity_name" not in row["ocsf"]
        assert row["summary"] == row["ocsf"]["message"] == expected
