"""scripts/fetch_ocsf_schema.py의 네트워크 없는 부분: 참조 추적과 처리하지 않는 제약 검사(#328)."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "fetch_ocsf_schema.py"
spec = importlib.util.spec_from_file_location("fetch_ocsf_schema", SCRIPT)
assert spec and spec.loader
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def test_references_lists_object_types_only():
    definition = {
        "attributes": {
            "a": {"type": "object_t", "object_type": "analytic"},
            "b": {"type": "string_t"},
            "c": {"type": "object_t", "object_type": "win/reg_key"},
        }
    }
    assert fetch.references(definition) == {"analytic", "win/reg_key"}


def test_unsupported_constraint_kinds_are_reported():
    known = {"attributes": {}, "constraints": {"at_least_one": ["a"], "just_one": ["b"]}}
    unknown = {"attributes": {}, "constraints": {"all_of": ["a"]}}
    assert fetch.unsupported_constraints(known) == set()
    assert fetch.unsupported_constraints(known, unknown) == {"all_of"}
