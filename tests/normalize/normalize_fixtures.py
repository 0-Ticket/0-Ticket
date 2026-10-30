"""Shared fixture loaders for the box 4 tests."""

import json
from pathlib import Path

from soc.contracts import SiemAlert, validate_contract
from soc.ingest.connector import source_record_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NORMALIZE = FIXTURES / "normalize"
OCSF = FIXTURES / "ocsf"
NOW = 1_800_000_000_000


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_ait_c2() -> list[SiemAlert]:
    return [
        validate_contract("SiemAlert", item)
        for item in read_json(FIXTURES / "ingest" / "expected_c2.json")
    ]


def make_c2(
    kind: str, mapping_profile: str, fields: dict, raw_ids: list[str] | None = None
) -> SiemAlert:
    content = {
        "kind": kind,
        "mapping_profile": mapping_profile,
        "raw_ids": raw_ids or ["raw_case_1"],
        "fields": fields,
    }
    return validate_contract(
        "SiemAlert", {**content, "source_record_id": source_record_id(content)}
    )


def fake_waf_c2() -> SiemAlert:
    item = read_json(NORMALIZE / "fake_waf_c2.json")
    return make_c2(item["kind"], item["mapping_profile"], item["fields"], item["raw_ids"])


def dump(model) -> dict:
    return model.model_dump(mode="json")
