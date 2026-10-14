"""Contract inventory and fixtures are reviewed by humans, never parsed from Markdown."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/contracts"
NAMES = """raw_record siem_alert alias_table normalized_alert normalize_failure event_record
asset_info user_info alert_record ticket verdict agent_step human_review incident incident_member
incident_artifact timeline_entry ioc recommendation specialist_finding l2_review case case_task
hunt_finding rule_proposal backtest vector_doc entity evidence""".split()


def read(path):
    return json.loads(path.read_text())


def schemas():
    return {p.name: read(p) for p in (ROOT / "contracts").glob("*.schema.json")}


def validator(name):
    items = schemas()
    registry = Registry().with_resources(
        (filename, Resource.from_contents(schema)) for filename, schema in items.items()
    )
    return Draft7Validator(items[name + ".schema.json"], registry=registry)


def fixture(name):
    return read(FIXTURES / "valid" / f"{name}.json")


def test_schema_contract_coverage():
    assert set(schemas()) == {n + ".schema.json" for n in NAMES}
    assert {p.stem for p in (FIXTURES / "valid").glob("*.json")} == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_structure_and_fixtures(name):
    schema = schemas()[name + ".schema.json"]
    Draft7Validator.check_schema(schema)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert set(schema["required"]) == set(schema["properties"]) == set(fixture(name))
    assert schema["additionalProperties"] is False
    validator(name).validate(fixture(name))
    for field in schema["required"]:
        value = fixture(name)
        del value[field]
        assert not validator(name).is_valid(value), field


@pytest.mark.parametrize("case", read(FIXTURES / "invalid/conditions.json"))
def test_structural_conditions(case):
    value = fixture(case["schema"]) | case["changes"]
    assert not validator(case["schema"]).is_valid(value)


@pytest.mark.parametrize(
    "name,field,bad",
    [
        ("normalized_alert", "severity_id", 7),
        ("normalized_alert", "class_uid", 1),
        ("asset_info", "criticality", 0),
        ("verdict", "confidence", 1.1),
        ("verdict", "evidence", []),
        ("ticket", "alert_ids", []),
        ("agent_step", "input_excerpt", "x" * 2001),
        ("agent_step", "step", 0),
        ("l2_review", "round", 0),
        ("ticket", "status", "custom"),
        ("raw_record", "received_at", "123"),
        ("raw_record", "raw_id", "wrong"),
    ],
)
def test_field_constraints(name, field, bad):
    assert not validator(name).is_valid(fixture(name) | {field: bad})


REGISTERED = {
    "raw_record": ["source_type"],
    "ticket": ["handling_type", "specialist"],
    "specialist_finding": ["specialist", "attack_type"],
    "ioc": ["type"],
    "entity": ["type"],
    "evidence": ["ref_type"],
    "vector_doc": ["collection"],
}


@pytest.mark.parametrize("name,fields", REGISTERED.items())
def test_registered_values(name, fields):
    value = fixture(name)
    for field in fields:
        prop = schemas()[name + ".schema.json"]["properties"][field]
        assert "enum" not in prop
        assert "description" in prop
        value[field] = "example.custom"
    validator(name).validate(value)


def test_alert_inherits_normalized_fields():
    items = schemas()
    normalized = items["normalized_alert.schema.json"]
    alert = items["alert_record.schema.json"]
    for name, field in normalized["properties"].items():
        assert alert["properties"][name] == field


@pytest.mark.parametrize("name", NAMES)
def test_extensions_and_unknown_fields(name):
    value = deepcopy(fixture(name))
    if "extensions" in value:
        value["extensions"] = {"example.new": {"nested": [None, True, 4, "sample"]}}
        validator(name).validate(value)
    value["undeclared"] = 1
    assert not validator(name).is_valid(value)


@pytest.mark.parametrize("name", NAMES)
def test_nullable_field_schemas(name):
    # Check the field in isolation; root if/then may legitimately require a value.
    for prop in schemas()[name + ".schema.json"]["properties"].values():
        registry = Registry().with_resources(
            (filename, Resource.from_contents(schema)) for filename, schema in schemas().items()
        )
        nullable = "null" in prop.get("type", []) or {"type": "null"} in prop.get("anyOf", [])
        assert Draft7Validator(prop, registry=registry).is_valid(None) == nullable


def test_all_references_are_local_and_resolve():
    items = schemas()

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"] in items
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for schema in items.values():
        walk(schema)


@pytest.mark.parametrize(
    "name,changes",
    [
        ("human_review", {"overturned": False, "reason": None}),
        ("incident_member", {"member_type": "hunt", "ticket_id": None, "hunt_id": "ht_sample"}),
        ("incident_member", {"excluded": True, "excluded_reason": "Sample reason"}),
        (
            "l2_review",
            {"decision": "reject", "reject_type": "missing_step", "comment": "Sample reason"},
        ),
        ("rule_proposal", {"hunt_id": None, "case_id": "cs_sample"}),
        ("normalized_alert", {"src_ip": None, "host": "web-01"}),
        ("alias_table", {"kind": "event", "class_uid": 4001, "severity_map": None}),
        ("agent_step", {"subject_type": "incident", "subject_id": "in_sample"}),
        ("agent_step", {"subject_type": "hunt", "subject_id": "ht_sample"}),
        ("agent_step", {"action": "tool_call", "tool": "sample"}),
        ("agent_step", {"action": "llm_call", "prompt_version": "sample-v1"}),
    ],
)
def test_condition_branches_accept_valid_values(name, changes):
    validator(name).validate(fixture(name) | changes)


def test_extension_key_namespace():
    assert not validator("user_info").is_valid(fixture("user_info") | {"extensions": {"plain": 1}})


@pytest.mark.parametrize("name", NAMES)
def test_empty_lists_follow_min_items(name):
    for field, prop in schemas()[name + ".schema.json"]["properties"].items():
        kind = prop.get("type")
        if kind == "array" or kind == ["array", "null"]:
            value = fixture(name) | {field: []}
            assert validator(name).is_valid(value) == (prop.get("minItems", 0) == 0)


@pytest.mark.parametrize(
    "anomaly,severity,valid",
    [
        (False, 0, True),
        (False, 1, False),
        (True, 0, True),
        (True, 6, True),
        (True, -1, False),
        (True, 7, False),
        (True, None, False),
    ],
)
def test_hunt_severity(anomaly, severity, valid):
    value = fixture("hunt_finding") | {"is_anomaly": anomaly, "severity_id": severity}
    assert validator("hunt_finding").is_valid(value) == valid
