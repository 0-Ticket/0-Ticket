"""Legacy C2/C12 storage compatibility converts fields in memory only."""

import json
from pathlib import Path

from soc.store.records.postgres import _with_mapping_profile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "store"


def test_legacy_siem_alert_conversion_keeps_input_unchanged():
    legacy = json.loads((FIXTURES / "legacy_siem_alert.json").read_text(encoding="utf-8"))

    current = _with_mapping_profile(legacy)

    assert current == {
        "kind": "alert",
        "mapping_profile": "legacy_profile",
        "raw_ids": ["raw_legacy_1"],
        "fields": {"message": "legacy"},
    }
    assert legacy["scenario"] == "legacy_profile"
    assert "mapping_profile" not in legacy


def test_legacy_normalize_failure_conversion_keeps_input_unchanged():
    legacy = json.loads((FIXTURES / "legacy_normalize_failure.json").read_text(encoding="utf-8"))

    current = _with_mapping_profile(legacy)

    assert current["mapping_profile"] == "legacy_profile"
    assert current["reason"] == "unknown_scenario"
    assert legacy["scenario"] == "legacy_profile"
    assert "mapping_profile" not in legacy
