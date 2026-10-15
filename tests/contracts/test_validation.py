"""Exercise the public runtime validation path, including installed package resources."""

import json
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from test_schemas import NAMES, REGISTERED, fixture, schemas

from soc.contracts import ContractValidationError, HuntFinding, validate_contract

ROOT = Path(__file__).resolve().parents[2]


def title(name):
    return schemas()[name + ".schema.json"]["title"]


def test_runtime_rejects_condition_accepted_by_generated_model():
    value = fixture("hunt_finding") | {"severity_id": 6}
    assert HuntFinding.model_validate(value).severity_id == 6
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("HuntFinding", value)
    assert caught.value.path == "/severity_id"
    assert caught.value.rule == "const"


@pytest.mark.parametrize("name", NAMES)
def test_runtime_valid_fixtures(name):
    result = validate_contract(title(name), fixture(name))
    assert result.model_dump(mode="json") == fixture(name)


@pytest.mark.parametrize("name,fields", REGISTERED.items())
def test_runtime_registered_values(name, fields):
    value = fixture(name) | {field: "example.custom" for field in fields}
    assert validate_contract(title(name), value).model_dump(mode="json") == value


def test_runtime_extensions():
    value = fixture("asset_info") | {"extensions": {"example.new": {"nested": [None, 1, True]}}}
    assert validate_contract("AssetInfo", value).model_dump(mode="json") == value


@pytest.mark.parametrize(
    "name,changes,path,rule",
    [
        ("raw_record", {"received_at": "UNTRUSTED_VALUE"}, "/received_at", "type"),
        ("user_info", {"extensions": {"UNTRUSTED_VALUE": 1}}, "/extensions", "pattern"),
        ("raw_record", {"UNTRUSTED_VALUE": "UNTRUSTED_VALUE"}, "/", "additionalProperties"),
        (
            "alias_table",
            {"severity_map": {"UNTRUSTED_VALUE": "UNTRUSTED_VALUE"}},
            "/severity_map/*",
            "type",
        ),
    ],
)
def test_errors_do_not_contain_input(name, changes, path, rule):
    with pytest.raises(ContractValidationError) as caught:
        validate_contract(title(name), fixture(name) | changes)
    error = caught.value
    assert error.path == path
    assert error.rule == rule
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "UNTRUSTED_VALUE" not in str(error)
    assert "UNTRUSTED_VALUE" not in repr(error)
    assert "UNTRUSTED_VALUE" not in repr(vars(error))
    assert "UNTRUSTED_VALUE" not in "".join(traceback.format_exception(error))


def test_missing_field_path():
    value = fixture("raw_record")
    del value["payload"]
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("RawRecord", value)
    assert (caught.value.path, caught.value.rule) == ("/payload", "required")


def test_nested_reference_conditions():
    value = fixture("incident")
    value["members"][0]["excluded"] = True
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("Incident", value)
    assert (caught.value.path, caught.value.rule) == ("/members/0/excluded_reason", "type")


def test_unknown_contract_does_not_echo_name():
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("UNTRUSTED_NAME", {})
    assert caught.value.rule == "unknown_contract"
    assert "UNTRUSTED_NAME" not in repr(caught.value)


def test_pydantic_failure_uses_same_safe_exception():
    # JSON Schema accepts mathematically integral numbers; StrictInt does not.
    with pytest.raises(ContractValidationError) as caught:
        validate_contract(
            "RawRecord", fixture("raw_record") | {"received_at": 1.0, "payload": "UNTRUSTED_VALUE"}
        )
    assert (caught.value.path, caught.value.rule) == ("/received_at", "int_type")
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "UNTRUSTED_VALUE" not in repr(vars(caught.value))
    assert "UNTRUSTED_VALUE" not in str(caught.value)


def test_validators_are_reused():
    with patch("soc.contracts.validation.Draft7Validator", side_effect=AssertionError("rebuilt")):
        for _ in range(2):
            validate_contract("RawRecord", fixture("raw_record"))
            validate_contract("HuntFinding", fixture("hunt_finding"))


def test_different_working_directory(tmp_path):
    code = (
        "import json; from soc.contracts import validate_contract; "
        f"data=json.loads({json.dumps(fixture('hunt_finding'))!r}); "
        'assert validate_contract("HuntFinding", data).severity_id == 0'
    )
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, check=True)


def test_wheel_contains_and_uses_schemas(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")], cwd=ROOT, check=True
    )
    wheel = next((tmp_path / "dist").glob("*.whl"))
    installed = tmp_path / "installed"
    with ZipFile(wheel) as archive:
        schema_files = [n for n in archive.namelist() if n.endswith(".schema.json")]
        assert len(schema_files) == len(NAMES)
        assert all(n.startswith("soc/contracts/schemas/") for n in schema_files)
        metadata = archive.read(next(n for n in archive.namelist() if n.endswith("/METADATA")))
        assert b"Requires-Dist: jsonschema" in metadata
        archive.extractall(installed)
    # Load only this built package, while using the test environment's dependencies.
    code = "\n".join(
        [
            "import sys, json",
            f"sys.path.insert(0, {str(installed)!r})",
            "import soc.contracts as contracts",
            f"assert contracts.__file__.startswith({str(installed)!r})",
            f"values=json.loads({json.dumps({title(n): fixture(n) for n in NAMES})!r})",
            "for name, data in values.items(): contracts.validate_contract(name, data)",
            'values["HuntFinding"]["severity_id"] = 6',
            'try: contracts.validate_contract("HuntFinding", values["HuntFinding"])',
            "except contracts.ContractValidationError: pass",
            'else: raise AssertionError("condition bypassed")',
        ]
    )
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, check=True)


@pytest.mark.parametrize("value", [None, 1791849602000])
def test_ticket_awaiting_human_at_values(value):
    ticket = fixture("ticket") | {"awaiting_human_at": value}
    if value is None:
        ticket["status"] = "triaging"
    result = validate_contract("Ticket", ticket)
    assert result.awaiting_human_at == value
    assert result.model_dump(mode="json")["awaiting_human_at"] == value


@pytest.mark.parametrize("value", ["1791849602000", True, 1.5, [], {}])
def test_ticket_awaiting_human_at_invalid_types(value):
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("Ticket", fixture("ticket") | {"awaiting_human_at": value})
    assert caught.value.path == "/awaiting_human_at"


def test_ticket_awaiting_human_at_required():
    ticket = fixture("ticket")
    del ticket["awaiting_human_at"]
    with pytest.raises(ContractValidationError) as caught:
        validate_contract("Ticket", ticket)
    assert (caught.value.path, caught.value.rule) == ("/awaiting_human_at", "required")


def test_ticket_wait_history_round_trip():
    # Authored snapshots, not a state-transition implementation or its test.
    history = json.loads((ROOT / "tests/fixtures/contracts/ticket_wait_history.json").read_text())
    results = [validate_contract("Ticket", ticket) for ticket in history]
    assert [result.status for result in results] == ["triaging", "awaiting_human", "closed_fp"]
    assert [result.awaiting_human_at for result in results] == [None, 1791849602000, 1791849602000]
    for ticket, result in zip(history, results, strict=True):
        serialized = json.loads(result.model_dump_json())
        assert serialized == ticket
        assert validate_contract("Ticket", serialized).model_dump(mode="json") == ticket
    assert results[1].awaiting_human_at != results[1].created_at
    assert results[2].awaiting_human_at != results[2].updated_at
