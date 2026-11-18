"""엔티티 항목의 when, 소스 표 entries의 덮어쓰기, GuardDuty 표 판별(#336)을 확인한다.

GuardDuty 샘플의 기대값은 alert_skeleton.json(test_alert_skeleton.py)이 지킨다.
"""

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest

from soc.ids import new_id
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.table_check import check_tables
from soc.normalize.tables import (
    TABLE_DIR,
    MappingTableError,
    apply_entities,
    load_tables,
    matching_source,
    parse_table,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize" / "mapping_tables"


def table_dir(tmp_path: Path, *fixtures: str) -> Path:
    """실제 common 표와 테스트용 소스 표를 한 폴더에 모은다."""
    shutil.copy(TABLE_DIR / "common.yaml", tmp_path / "common.yaml")
    for name in fixtures:
        shutil.copy(FIXTURES / f"{name}.yaml", tmp_path / f"{name.removeprefix('source_')}.yaml")
    return tmp_path


def alert(source: dict[str, Any]) -> RawRow:
    """_source만 바꿔 쓰는 최소 알럿 원본."""
    base = {
        "kibana.alert.uuid": "u-1",
        "kibana.alert.start": "2026-11-13T00:00:00.000Z",
        "kibana.alert.original_time": "2026-11-12T23:59:00.000Z",
        "kibana.alert.rule.name": "Rule Name",
        "kibana.alert.rule.description": "Rule Description",
        "kibana.alert.rule.rule_id": "r-1",
        "kibana.alert.severity": "high",
    }
    original = {"_id": "h-1", "_index": "i", "_source": {**base, **copy.deepcopy(source)}}
    return RawRow(id=new_id("raw"), kind="alert", original=original)


# --- when 로더 ---


def test_when_loads_with_field_string_or_list(tmp_path):
    table = load_tables(table_dir(tmp_path, "source_when_ok"))["when_ok"]
    first, second = table.entities
    assert (first.when.fields, first.when.equals) == (("direction",), "IN")
    assert (second.when.fields, second.when.equals) == (("direction_old", "direction"), "OUT")


@pytest.mark.parametrize(
    "fixture",
    [
        "source_bad_when_unknown_key",
        "source_bad_when_no_field",
        "source_bad_when_equals_type",
        "source_bad_when_exists",
        "source_bad_when_shape",
    ],
)
def test_bad_when_fails_at_load_time(tmp_path, fixture):
    with pytest.raises(MappingTableError, match="when"):
        load_tables(table_dir(tmp_path, fixture))


# --- when 적용 ---


def when_table():
    return parse_table(
        "t",
        {
            "entries": [],
            "entities": [
                {
                    "type": "ip",
                    "role": "src",
                    "from": ["ip"],
                    "when": {"field": ["d"], "equals": "IN"},
                },
                {
                    "type": "ip",
                    "role": "dst",
                    "from": ["ip"],
                    "when": {"field": ["d"], "equals": "OUT"},
                },
            ],
        },
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"d": "IN", "ip": "192.0.2.1"}, [("ip", "192.0.2.1", "src")]),
        ({"d": "OUT", "ip": "192.0.2.1"}, [("ip", "192.0.2.1", "dst")]),
        ({"d": "SIDE", "ip": "192.0.2.1"}, []),
        ({"ip": "192.0.2.1"}, []),
    ],
)
def test_when_applies_the_item_only_if_the_field_equals_the_value(source, expected):
    applied = apply_entities(when_table(), {"_source": source})
    assert [(e["type"], e["value"], e["role"]) for e in applied.entities] == expected


def test_a_skipped_when_item_reports_no_missing_path():
    table = parse_table(
        "t",
        {
            "entries": [],
            "entities": [
                {
                    "type": "ip",
                    "role": "src",
                    "from": ["ip"],
                    "transform": "ip",
                    "when": {"field": "d", "equals": "IN"},
                }
            ],
        },
    )
    applied = apply_entities(table, {"_source": {"d": "OUT", "ip": "not-an-ip"}})
    assert applied.entities == [] and applied.missing == []


# --- 소스 표 entries의 덮어쓰기 ---


def test_guardduty_title_and_description_override_the_rule_text():
    row = normalize(
        alert({"guardduty": {"title": "GD title", "description": "GD description"}})
    ).row
    assert row["title"] == row["ocsf"]["finding_info"]["title"] == "GD title"
    assert row["ocsf"]["finding_info"]["desc"] == "GD description"
    assert row["ocsf"]["message"] == "GD description"
    # 룰 이름은 분석 규칙 이름으로 남는다
    assert row["ocsf"]["finding_info"]["analytic"]["name"] == "Rule Name"


def test_missing_guardduty_text_keeps_the_common_values():
    result = normalize(alert({"guardduty": {"type": "x"}}))
    row = result.row
    assert row["title"] == "Rule Name"
    assert row["ocsf"]["finding_info"]["desc"] == row["ocsf"]["message"] == "Rule Description"
    assert (result.outcome, result.missing_fields) == ("ok", ())


def test_non_guardduty_sources_ignore_guardduty_entries():
    row = normalize(alert({"event": {"module": "suricata"}})).row
    assert row["title"] == "Rule Name"


# --- 판별 ---


def test_repository_guardduty_table_loads_and_passes_the_checker():
    tables = load_tables()
    assert "guardduty" in tables and tables["guardduty"].detect
    assert check_tables(tables) == []


def test_guardduty_key_decides_the_source_without_code():
    assert normalize(alert({"guardduty": {"type": "x"}})).source == "guardduty"
    assert normalize(alert({})).source == "unknown"


def test_guardduty_key_that_is_not_an_object_still_counts_but_null_does_not():
    assert normalize(alert({"guardduty": "text"})).source == "guardduty"
    assert normalize(alert({"guardduty": None})).source == "unknown"


def test_tables_are_checked_by_name_so_guardduty_wins_over_suricata():
    # 현재 동작의 문서화: 표 이름 순이라 event.module보다 guardduty 키가 먼저 맞는다
    # (실제 GuardDuty 알럿에는 event.module이 없다)
    source = {"event": {"module": "suricata"}, "guardduty": {"type": "x"}}
    assert matching_source(load_tables(), {"_source": source}) == "guardduty"
    assert normalize(alert(source)).source == "guardduty"


def test_other_sources_are_unchanged_by_the_guardduty_table():
    assert normalize(alert({"event": {"module": "suricata"}})).source == "suricata"
    assert normalize(alert({"event": {"module": "modsecurity"}})).source == "modsecurity"
