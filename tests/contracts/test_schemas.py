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
hunt_finding rule_proposal backtest vector_doc entity evidence branch_result evidence_request
l1_decision_record""".split()


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
        ("event_record", "http_bytes", -1),
        ("asset_info", "criticality", 0),
        ("verdict", "confidence", 1.1),
        ("verdict", "evidence", []),
        ("ticket", "alert_ids", []),
        ("agent_step", "input_excerpt", "x" * 2001),
        ("agent_step", "step", 0),
        ("l2_review", "round", 0),
        ("ticket", "status", "custom"),
        ("ticket", "origin", "custom"),
        ("siem_alert", "source_record_id", "raw_source"),
        ("alert_record", "source_record_id", "raw_source"),
        ("event_record", "source_record_id", "raw_source"),
        ("branch_result", "branch_id", "wrong"),
        ("evidence_request", "request_id", "wrong"),
        ("l1_decision_record", "decision_id", "wrong"),
        ("raw_record", "received_at", "123"),
        ("raw_record", "raw_id", "wrong"),
    ],
)
def test_field_constraints(name, field, bad):
    assert not validator(name).is_valid(fixture(name) | {field: bad})


@pytest.mark.parametrize(
    "name,field",
    [
        ("siem_alert", "mapping_profile"),
        ("alias_table", "tool"),
        ("alias_table", "log_type"),
        ("alias_table", "mapping_profile"),
        ("normalize_failure", "mapping_profile"),
    ],
)
def test_mapping_selectors_are_non_empty(name, field):
    assert not validator(name).is_valid(fixture(name) | {field: ""})


@pytest.mark.parametrize("reason", ["unknown_scenario", "unknown_mapping_profile"])
def test_normalize_failure_accepts_legacy_and_mapping_profile_reasons(reason):
    value = fixture("normalize_failure") | {"reason": reason}
    validator("normalize_failure").validate(value)


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


def test_normalized_records_reference_the_original_c2_id():
    source_alert = fixture("siem_alert")
    alert = fixture("alert_record")
    source_event = source_alert | {
        "kind": "event",
        "source_record_id": "src_event_sample",
    }
    event = fixture("event_record")

    validator("siem_alert").validate(source_alert)
    validator("siem_alert").validate(source_event)
    validator("alert_record").validate(alert)
    validator("event_record").validate(event)
    assert alert["source_record_id"] == source_alert["source_record_id"]
    assert event["source_record_id"] == source_event["source_record_id"]
    assert alert["raw_ids"] == source_alert["raw_ids"]


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
        ("agent_step", {"subject_type": "ticket", "subject_id": "tk_sample"}),
        ("agent_step", {"subject_type": "incident", "subject_id": "in_sample"}),
        ("agent_step", {"subject_type": "hunt", "subject_id": "ht_sample"}),
        ("agent_step", {"subject_type": "alert", "subject_id": "al_sample"}),
        ("agent_step", {"action": "tool_call", "tool": "sample"}),
        ("agent_step", {"action": "llm_call", "prompt_version": "sample-v1"}),
        ("ticket", {"status": "on_hold"}),
        ("ticket", {"status": "l2_escalated"}),
        (
            "branch_result",
            {"subject_type": "ticket", "subject_id": "tk_sample", "path": "existing_incident"},
        ),
        (
            "evidence_request",
            {
                "domain": None,
                "request_type": "lookup",
                "params": {"entity": {"type": "ip", "value": "192.0.2.10"}, "at": None},
                "status": "completed",
                "result": {"asset": None, "user": None},
            },
        ),
        (
            "evidence_request",
            {"status": "failed", "failure_reason": "Synthetic timeout", "retry_count": 1},
        ),
        (
            "l1_decision_record",
            {
                "subject_type": "ticket",
                "subject_id": "tk_sample",
                "decision": "held",
                "confidence": None,
                "reason": "evidence_request_failure",
            },
        ),
        (
            "l1_decision_record",
            {
                "subject_type": "ticket",
                "subject_id": "tk_sample",
                "decision": "l2_escalated",
            },
        ),
    ],
)
def test_condition_branches_accept_valid_values(name, changes):
    validator(name).validate(fixture(name) | changes)


ENTITY = {"type": "ip", "value": "192.0.2.10"}
SIEM_PARAMS = {
    "entity": ENTITY,
    "kind": "event",
    "start_at": 1791849000000,
    "end_at": 1791849600000,
    "limit": 50,
}
ALERT_SIEM = {
    "requester_type": "alert",
    "requester_id": "al_sample",
    "request_type": "siem_mcp",
    "domain": None,
    "params": SIEM_PARAMS,
}
ALERT_LOOKUP = ALERT_SIEM | {
    "request_type": "lookup",
    "params": {"entity": ENTITY, "at": 1791849600000},
}
COMPLETED = {"status": "completed"}


@pytest.mark.parametrize(
    "changes",
    [
        ALERT_SIEM,
        ALERT_SIEM | COMPLETED | {"result": {"records": [fixture("siem_alert")]}},
        ALERT_SIEM | COMPLETED | {"result": {"records": []}},
        ALERT_LOOKUP | {"params": {"entity": ENTITY, "at": None}},
        ALERT_LOOKUP | COMPLETED | {"result": {"asset": fixture("asset_info"), "user": None}},
        ALERT_LOOKUP | COMPLETED | {"result": {"asset": None, "user": fixture("user_info")}},
        ALERT_SIEM | {"status": "failed", "failure_reason": "Synthetic timeout", "retry_count": 2},
        COMPLETED | {"result": {"finding": fixture("specialist_finding")}},
        {"status": "in_progress"},
        ALERT_LOOKUP | {"requester_type": "incident", "requester_id": "in_sample"},
        {"requester_type": "incident", "requester_id": "in_sample"},
    ],
)
def test_evidence_request_branches_accept_valid_values(changes):
    validator("evidence_request").validate(fixture("evidence_request") | changes)


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


@pytest.mark.parametrize(
    "state,round_,valid",
    [
        ("awaiting_review", 1, True),
        ("awaiting_review", 3, True),
        ("awaiting_review", None, False),
        ("awaiting_review", 0, False),
        ("analyzing", None, True),
        ("analyzing", 1, False),
        ("approved", None, True),
        ("approved", 1, False),
        ("human_handling", None, True),
        ("human_handling", 2, False),
        ("analyzing", 0, False),
        ("example.custom", None, False),
    ],
)
def test_incident_review_state_round_pairing(state, round_, valid):
    value = fixture("incident") | {"review_state": state, "review_round": round_}
    assert validator("incident").is_valid(value) == valid


def test_incident_review_state_is_closed_enum_like_status():
    # review_state is a fixed workflow enum like C10 status, not a registered value.
    props = schemas()["incident.schema.json"]["properties"]
    assert "incident" not in REGISTERED
    for field in ("status", "review_state"):
        assert props[field]["type"] == "string"
        assert "enum" in props[field]
