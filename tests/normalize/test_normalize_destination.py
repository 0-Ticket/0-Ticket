"""손으로 만든 목적지 샘플의 엔티티·클래스별 본문·검증 경계를 확인한다."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import validate_contract
from soc.ids import new_id
from soc.normalize.errors import NormalizeError
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.ocsf_schema import validate_ocsf

CASES = json.loads(
    (Path(__file__).parent.parent / "fixtures/normalize/destination.json").read_text()
)

BY_CASE = {case["case"]: case for case in CASES}
OMISSION_CASES = [
    BY_CASE[name]
    for name in ("alert_flat_destination", "web_nested", "cloud_ipv6", "base_destination")
]


def convert(case: dict[str, Any]) -> dict[str, Any]:
    raw = RawRow(new_id("raw"), case["kind"], copy.deepcopy(case["original"]))
    before = copy.deepcopy(raw.original)
    result = normalize(raw)
    assert raw.original == before
    validate_contract(result.kind, result.row)
    validate_ocsf(result.row["ocsf"])
    return result.row


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
def test_destination_is_preserved(case: dict[str, Any]) -> None:
    row = convert(case)
    assert {"type": "ip", "value": case["destination"], "role": "dst"} in row["entities"]
    src = case["original"]["_source"].get("source.ip")
    assert [e for e in row["entities"] if e["role"] == "src"] == (
        [{"type": "ip", "value": src, "role": "src"}] if src else []
    )
    ocsf = row["ocsf"]
    if ocsf["class_uid"] == 2004:
        assert ocsf["evidences"] == [{"dst_endpoint": {"ip": case["destination"]}}]
        assert "dst_endpoint" not in ocsf
    elif ocsf["class_uid"] in (4002, 6003):
        assert ocsf["dst_endpoint"] == {"ip": case["destination"]}
    else:
        assert ocsf["unmapped"] == {"destination": {"ip": case["destination"]}}
        assert "dst_endpoint" not in ocsf


@pytest.mark.parametrize("case", OMISSION_CASES, ids=lambda case: case["case"])
@pytest.mark.parametrize("value", [None, "", "  ", 42, True, [], ["192.0.2.20"], {}])
def test_invalid_flat_destination_does_not_fall_back_or_create_empty_objects(
    case: dict[str, Any], value: Any
) -> None:
    case = copy.deepcopy(case)
    source = case["original"]["_source"]
    source["destination.ip"] = value
    source["destination"] = {"ip": "192.0.2.99"}
    row = convert(case)
    assert not any(e["role"] == "dst" for e in row["entities"])
    assert "dst_endpoint" not in row["ocsf"]
    assert "evidences" not in row["ocsf"]
    assert "unmapped" not in row["ocsf"]
    assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in row["entities"]


@pytest.mark.parametrize("case", OMISSION_CASES, ids=lambda case: case["case"])
def test_missing_destination_is_omitted(case: dict[str, Any]) -> None:
    case = copy.deepcopy(case)
    source = case["original"]["_source"]
    source.pop("destination.ip", None)
    source.pop("destination", None)
    row = convert(case)
    assert not any(e["role"] == "dst" for e in row["entities"])
    assert "dst_endpoint" not in row["ocsf"]
    assert "evidences" not in row["ocsf"]
    assert "unmapped" not in row["ocsf"]


@pytest.mark.parametrize(
    "evidences",
    [
        {},
        [1],
        [{"dst_endpoint": []}],
        [{"dst_endpoint": {"ip": 42}}],
        [{"dst_endpoint": {"unknown": "x"}}],
        [{"unknown": "x"}],
    ],
)
def test_malformed_evidences_are_rejected(evidences: Any) -> None:
    ocsf = convert(BY_CASE["alert_flat_destination"])["ocsf"]
    ocsf["evidences"] = evidences
    with pytest.raises(NormalizeError, match="schema_failed"):
        validate_ocsf(ocsf)


@pytest.mark.parametrize(
    "case",
    [BY_CASE["alert_flat_destination"], BY_CASE["base_destination"]],
    ids=lambda case: case["case"],
)
def test_unsupported_top_level_destination_is_rejected(case: dict[str, Any]) -> None:
    ocsf = convert(case)["ocsf"]
    ocsf["dst_endpoint"] = {"ip": "192.0.2.20"}
    with pytest.raises(NormalizeError, match="schema_failed"):
        validate_ocsf(ocsf)


@pytest.mark.parametrize(
    "unmapped",
    [{}, {"destination": {"ip": "192.0.2.20"}}, {"nested": [None, True, 1, 1.5, "text", [], {}]}],
)
def test_generic_unmapped_accepts_json_objects(unmapped: dict[str, Any]) -> None:
    ocsf = convert(BY_CASE["alert_flat_destination"])["ocsf"]
    ocsf["unmapped"] = unmapped
    validate_ocsf(ocsf)


@pytest.mark.parametrize(
    "unmapped",
    [
        None,
        [],
        "text",
        1,
        {"value": object()},
        {"value": (1, 2)},
        {1: "value"},
        {"nested": [{1: "value"}]},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
    ],
)
def test_generic_unmapped_rejects_non_json_values(unmapped: Any) -> None:
    ocsf = convert(BY_CASE["alert_flat_destination"])["ocsf"]
    ocsf["unmapped"] = unmapped
    with pytest.raises(NormalizeError, match="schema_failed"):
        validate_ocsf(ocsf)


def test_generic_unmapped_does_not_allow_unknown_top_level_attributes() -> None:
    ocsf = convert(BY_CASE["alert_flat_destination"])["ocsf"]
    ocsf["unmapped"] = {"destination": {"ip": "192.0.2.20"}}
    ocsf["unknown"] = {"ip": "192.0.2.20"}
    with pytest.raises(NormalizeError, match="schema_failed"):
        validate_ocsf(ocsf)


@pytest.mark.parametrize("endpoint", [[], {"ip": 42}, {"unknown": "value"}])
def test_known_network_object_remains_strict(endpoint: Any) -> None:
    ocsf = convert(BY_CASE["web_nested"])["ocsf"]
    ocsf["dst_endpoint"] = endpoint
    with pytest.raises(NormalizeError, match="schema_failed"):
        validate_ocsf(ocsf)
