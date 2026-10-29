"""One runtime validation path for contract objects and decoded LLM JSON."""

import json
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft7Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

from . import generated


class ContractValidationError(ValueError):
    """A safe field path and rule only; never retain input or a provider exception."""

    def __init__(self, path: str, rule: str):
        self.path = path
        self.rule = rule
        super().__init__(f"{path}: {rule}")


def _schema_directory():
    packaged = files(__package__).joinpath("schemas")
    if packaged.is_dir():
        return packaged
    # Editable installs expose src/ directly. Resolve from this module, never cwd.
    module_dir = Path(__file__).resolve().parent
    root = module_dir.parents[2]
    if module_dir == root / "src/soc/contracts" and (root / "contracts").is_dir():
        return root / "contracts"
    raise RuntimeError("Packaged contract schemas are missing")


def _load_contracts():
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_schema_directory().iterdir(), key=lambda p: p.name)
        if path.name.endswith(".schema.json")
    ]
    # No retrieval callback: references can only resolve against bundled resources.
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    contracts = {}
    field_names = set()
    for schema in schemas:
        Draft7Validator.check_schema(schema)
        contracts[schema["title"]] = (
            Draft7Validator(schema, registry=registry),
            getattr(generated, schema["title"]),
        )
        field_names.update(schema["properties"])
    return contracts, frozenset(field_names)


# Python's module import lock ensures each validator is constructed once, even
# when callers arrive concurrently. Validators and the local registry are reused.
_CONTRACTS, _FIELD_NAMES = _load_contracts()


def _safe_path(parts):
    # Dictionary keys can be log content. Emit only schema-declared field names
    # and list indexes; mask other segments instead of echoing user-controlled keys.
    safe = [str(p) if isinstance(p, int) or p in _FIELD_NAMES else "*" for p in parts]
    return "/" + "/".join(safe)


def _schema_failure(validator, data):
    error = next(validator.iter_errors(data), None)
    if error is None:
        return None
    path = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = next(field for field in error.validator_value if field not in error.instance)
        path.append(missing)
    # Do not return the original error: its instance/message/context contain data.
    return _safe_path(path), error.validator


def _convert(model, data):
    try:
        return model.model_validate(data), None
    except ValidationError as error:
        first = error.errors(include_input=False, include_context=False, include_url=False)[0]
        return None, (_safe_path(first["loc"]), first["type"])


def validate_contract(name: str, data: object) -> BaseModel:
    """Validate decoded JSON by schema title, then return its generated model.

    Raises ContractValidationError with only ``path`` (JSON pointer, unknown keys
    masked as '*') and ``rule``. No input values or original exceptions are attached.
    Registered strings are structurally accepted; registration and other business
    rules remain the responsibility of the relevant box.
    """
    contract = _CONTRACTS.get(name) if isinstance(name, str) else None
    if contract is None:
        raise ContractValidationError("/", "unknown_contract")
    validator, model = contract
    failure = _schema_failure(validator, data)
    if failure is not None:
        raise ContractValidationError(*failure)
    result, failure = _convert(model, data)
    if failure is not None:
        # Raise outside the except block so __context__ cannot retain ValidationError.
        raise ContractValidationError(*failure)
    return result
