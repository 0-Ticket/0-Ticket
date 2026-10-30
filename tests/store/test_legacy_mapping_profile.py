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
        "source_record_id": "src_5a214ca80f13915b5b2519f0b16bd84654207b0d4d7d91d10fb0d7df688226c0",
        "mapping_profile": "legacy_profile",
        "raw_ids": ["raw_legacy_1"],
        "fields": {"message": "legacy"},
    }
    assert legacy["scenario"] == "legacy_profile"
    assert "mapping_profile" not in legacy


def test_legacy_siem_event_conversion_keeps_input_unchanged():
    legacy = json.loads((FIXTURES / "legacy_siem_event.json").read_text(encoding="utf-8"))

    current = _with_mapping_profile(legacy)

    assert current["kind"] == "event"
    assert current["source_record_id"] == (
        "src_03e4d45594e708f491d516cf4f5e2fdf9d6cbd76550dc65bb33d03a25555e363"
    )
    assert current["mapping_profile"] == "legacy_profile"
    assert legacy["scenario"] == "legacy_profile"
    assert "mapping_profile" not in legacy


def test_legacy_normalize_failure_conversion_keeps_input_unchanged():
    legacy = json.loads((FIXTURES / "legacy_normalize_failure.json").read_text(encoding="utf-8"))

    current = _with_mapping_profile(legacy)

    assert current["mapping_profile"] == "legacy_profile"
    assert current["reason"] == "unknown_scenario"
    assert legacy["scenario"] == "legacy_profile"
    assert "mapping_profile" not in legacy
