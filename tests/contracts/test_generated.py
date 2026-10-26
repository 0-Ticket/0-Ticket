import importlib

import pytest
from pydantic import ValidationError
from test_schemas import NAMES, REGISTERED, fixture, schemas


def model(name):
    module = importlib.import_module("soc.contracts")
    return getattr(module, schemas()[name + ".schema.json"]["title"])


@pytest.mark.parametrize("name", NAMES)
def test_generated_round_trip(name):
    value = fixture(name)
    assert model(name).model_validate(value).model_dump(mode="json") == value
    assert set(model(name).model_fields) == set(value)
    for field in value:
        missing = value.copy()
        del missing[field]
        with pytest.raises(ValidationError):
            model(name).model_validate(missing)


@pytest.mark.parametrize("name", NAMES)
def test_generated_nullable_fields(name):
    for field, prop in schemas()[name + ".schema.json"]["properties"].items():
        nullable = "null" in prop.get("type", []) or {"type": "null"} in prop.get("anyOf", [])
        value = fixture(name) | {field: None}
        if nullable:
            assert model(name).model_validate(value).model_dump(mode="json")[field] is None
        else:
            with pytest.raises(ValidationError):
                model(name).model_validate(value)


@pytest.mark.parametrize("name", NAMES)
def test_generated_forbids_unknown_fields(name):
    with pytest.raises(ValidationError):
        model(name).model_validate(fixture(name) | {"undeclared": 1})


@pytest.mark.parametrize("name,fields", REGISTERED.items())
def test_generated_registered_values(name, fields):
    value = fixture(name) | {field: "example.custom" for field in fields}
    assert model(name).model_validate(value).model_dump(mode="json") == value


@pytest.mark.parametrize("name", NAMES)
def test_generated_strict_field_types(name):
    for field, prop in schemas()[name + ".schema.json"]["properties"].items():
        kind = prop.get("type")
        if isinstance(kind, list):
            kind = kind[0]
        bad = {
            "string": 123,
            "integer": "123",
            "number": "0.5",
            "boolean": "true",
            "array": {},
            "object": [],
        }.get(kind)
        if bad is not None:
            with pytest.raises(ValidationError):
                model(name).model_validate(fixture(name) | {field: bad})


@pytest.mark.parametrize(
    "name,field,bad",
    [
        ("normalized_alert", "severity_id", 7),
        ("hunt_finding", "severity_id", -1),
        ("hunt_finding", "severity_id", 7),
        ("normalized_alert", "class_uid", 1),
        ("event_record", "http_bytes", -1),
        ("asset_info", "criticality", 6),
        ("verdict", "confidence", -0.1),
        ("verdict", "evidence", []),
        ("ticket", "alert_ids", []),
        ("agent_step", "output_excerpt", "x" * 2001),
        ("agent_step", "step", 0),
        ("l2_review", "round", 0),
        ("ticket", "status", "custom"),
        ("incident", "review_round", 0),
        ("incident", "review_state", "custom"),
    ],
)
def test_generated_field_constraints(name, field, bad):
    with pytest.raises(ValidationError):
        model(name).model_validate(fixture(name) | {field: bad})


def test_id_lists_are_strings():
    for name, field in [
        ("normalized_alert", "raw_ids"),
        ("alert_record", "raw_ids"),
        ("siem_alert", "raw_ids"),
        ("ticket", "alert_ids"),
    ]:
        value = model(name).model_validate(fixture(name))
        assert all(isinstance(item, str) for item in getattr(value, field))
