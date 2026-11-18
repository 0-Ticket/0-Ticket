"""고정한 OCSF 1.9.0 정의(클래스 8개와 참조 객체 138개)와 스키마 로더를 검사한다(#328, #340)."""

import json
from pathlib import Path

import pytest

from soc.normalize import ocsf_schema
from soc.normalize.ocsf_schema import (
    SUPPORTED_CONSTRAINTS,
    field_definition,
    validate_ocsf,
)

OCSF_DIR = Path(ocsf_schema.__file__).parent / "ocsf"


def _objects() -> dict:
    return json.loads((OCSF_DIR / "objects.json").read_text(encoding="utf-8"))


def test_pinned_schema_is_the_full_closure_of_the_pinned_classes():
    objects = _objects()
    assert len(objects) == 138
    for uid in (0, 2003, 2004, 3002, 4001, 4002, 4003, 6003):
        definition = json.loads((OCSF_DIR / "classes" / f"{uid}.json").read_text(encoding="utf-8"))
        assert definition["uid"] == uid
        assert "caption" in definition and "description" in definition
    # 모든 object_type이 같은 파일 안에서 풀린다
    for definition in objects.values():
        for attribute in definition["attributes"].values():
            if attribute["type"] == "object_t":
                assert attribute["object_type"] in objects


def test_every_pinned_constraint_kind_is_supported():
    kinds = {kind for object_ in _objects().values() for kind in object_.get("constraints", {})}
    assert kinds <= SUPPORTED_CONSTRAINTS
    assert {"at_least_one", "just_one"} <= SUPPORTED_CONSTRAINTS


def test_field_definition_reads_type_requirement_and_enum_by_path():
    analytic_uid = field_definition(2004, "finding_info.analytic.uid")
    assert analytic_uid["type"] == "string_t"
    assert analytic_uid["requirement"] == "recommended"
    severity = field_definition(2004, "severity_id")
    assert severity["requirement"] == "required"
    assert "4" in severity["enum"]
    assert field_definition(0, "message")["type"] == "string_t"


def test_field_definition_follows_array_paths():
    ip = field_definition(2004, "evidences[].dst_endpoint.ip")
    assert ip is not None and ip["type"] == "ip_t"
    assert field_definition(2004, "evidences")["is_array"] is True


@pytest.mark.parametrize(
    "path",
    ["finding_info.analytic.nope", "nope", "finding_info.title.deeper", "finding_info..uid", ""],
)
def test_field_definition_returns_none_for_unknown_paths(path):
    assert field_definition(2004, path) is None


def test_field_definition_returns_none_for_unknown_class():
    assert field_definition(9999, "time") is None


@pytest.mark.parametrize(
    ("kind", "good", "bad"),
    [
        ("float_t", [1.5, 2, 0.0], [True, "1.5", float("inf"), float("nan")]),
        ("json_t", [{"a": [1, None]}, [1, "x"], "text", 3, None], [{1: "x"}, {"a": float("nan")}]),
        ("bytestring_t", ["YWJj"], [1, None]),
        ("ip_t", ["10.0.0.1"], [1]),
        ("string_t", ["x"], [1, True]),
        ("integer_t", [1], [True, "1", 1.5]),
        ("boolean_t", [True], [1, "true"]),
    ],
)
def test_attribute_value_types(kind, good, bad):
    attribute = {"type": kind}
    for value in good:
        assert ocsf_schema._attribute_is_valid(attribute, value), (kind, value)
    for value in bad:
        assert not ocsf_schema._attribute_is_valid(attribute, value), (kind, value)


def test_just_one_constraint_needs_exactly_one_listed_attribute():
    definition = {
        "attributes": {
            "a": {"type": "string_t", "requirement": "optional"},
            "b": {"type": "string_t", "requirement": "optional"},
        },
        "constraints": {"just_one": ["a", "b"]},
    }
    assert ocsf_schema._object_is_valid(definition, {"a": "x"})
    assert not ocsf_schema._object_is_valid(definition, {})
    assert not ocsf_schema._object_is_valid(definition, {"a": "x", "b": "y"})


def test_enum_in_pinned_shape_checks_keys():
    attribute = {"type": "integer_t", "enum": {"1": {"caption": "New"}, "2": {"caption": "X"}}}
    assert ocsf_schema._attribute_is_valid(attribute, 2)
    assert not ocsf_schema._attribute_is_valid(attribute, 3)


def test_full_closure_lets_official_objects_through_but_still_checks_them():
    base = {
        "class_uid": 2004,
        "category_uid": 2,
        "activity_id": 1,
        "type_uid": 200401,
        "severity_id": 3,
        "time": 1,
        "metadata": {"version": "1.9.0", "product": {"name": "Elasticsearch"}},
        "finding_info": {
            "uid": "u",
            "title": "t",
            "analytic": {"name": "r", "type_id": 1},
        },
    }
    validate_ocsf(base)
    # 줄인 정의는 막았던 공식 객체(related_analytics)가 이제 통과한다(#328 바뀐 점)
    base["finding_info"]["related_analytics"] = [{"name": "other", "type_id": 1}]
    validate_ocsf(base)
    # 정의에 없는 속성과 잘못된 enum은 여전히 실패한다
    base["finding_info"]["analytic"]["type_id"] = 12345
    with pytest.raises(ocsf_schema.NormalizeError):
        validate_ocsf(base)
