"""선언형 매핑표(#328): 로더, 변환 등록부, 값 읽기, detect, 검증기, 시작 시점 오류를 확인한다.

테스트용 표는 tests/fixtures/normalize/mapping_tables/에 손으로 쓴 작은 파일이다.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from soc.contracts import to_epoch_ms
from soc.normalize import run as run_module
from soc.normalize import tables as tables_module
from soc.normalize.__main__ import main
from soc.normalize.config import Settings
from soc.normalize.table_check import check_tables
from soc.normalize.tables import (
    MappingTableError,
    Table,
    apply_table,
    load_tables,
    matching_source,
)
from soc.normalize.transforms import TRANSFORMS

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize" / "mapping_tables"
REAL_COMMON = Path(tables_module.__file__).parent / "mapping_tables" / "common.yaml"
COMMON_TARGETS = [
    "finding_info.title",
    "finding_info.desc",
    "finding_info.uid",
    "finding_info.analytic.uid",
    "finding_info.analytic.name",
    "severity_id",
    "risk_score",
    "message",
    "time",
    "finding_info.created_time",
]


def table_dir(tmp_path: Path, *fixtures: str, common: dict[str, Any] | None = None) -> Path:
    """실제 common 표(또는 common 대체)와 테스트용 소스 표를 한 폴더에 모은다."""
    if common is None:
        shutil.copy(REAL_COMMON, tmp_path / "common.yaml")
    else:
        (tmp_path / "common.yaml").write_text(yaml.safe_dump(common), encoding="utf-8")
    for name in fixtures:
        shutil.copy(FIXTURES / f"{name}.yaml", tmp_path / f"{name.removeprefix('source_')}.yaml")
    return tmp_path


def real_common() -> dict[str, Any]:
    return yaml.safe_load(REAL_COMMON.read_text(encoding="utf-8"))


def table_of(entries: list[dict[str, Any]]) -> Table:
    """항목 목록으로 임시 common 표를 만들어 로드한다(로더를 거친다)."""
    return tables_module.parse_table("t", {"entries": entries})


# --- 로더 ---


def test_repository_tables_load_and_common_holds_the_nine_simple_rules():
    common = load_tables()["common"]
    assert [entry.target for entry in common.entries] == COMMON_TARGETS
    required = [entry.target for entry in common.entries if entry.required]
    assert required == ["finding_info.analytic.uid", "severity_id"]
    assert common.detect == ()


def test_source_table_loads_with_detect_and_array_targets(tmp_path):
    tables = load_tables(table_dir(tmp_path, "source_ok"))
    assert set(tables) == {"common", "ok"}
    assert [c.field for c in tables["ok"].detect] == [
        "event.module",
        "kibana.alert.original_event.module",
    ]
    assert tables["ok"].entries[0].target == "evidences[].src_endpoint.ip"


@pytest.mark.parametrize(
    "fixture",
    ["source_unknown_transform", "source_bad_detect", "source_unsafe", "source_duplicate_target"],
)
def test_bad_tables_fail_at_load_time(tmp_path, fixture):
    with pytest.raises(MappingTableError):
        load_tables(table_dir(tmp_path, fixture))


def test_unknown_transform_error_names_the_transform(tmp_path):
    with pytest.raises(MappingTableError, match="shell"):
        load_tables(table_dir(tmp_path, "source_unknown_transform"))


def test_common_table_is_required(tmp_path):
    (tmp_path / "x.yaml").write_text("entries: []\n", encoding="utf-8")
    with pytest.raises(MappingTableError, match="common"):
        load_tables(tmp_path)


@pytest.mark.parametrize(
    "document",
    [
        "- not a mapping\n",
        "entries: {}\n",
        "entries: []\nextra: 1\n",
        "entries:\n  - {target: severity_id}\n",
        "entries:\n  - {target: severity_id, from: []}\n",
        "entries:\n  - {target: severity_id, from: [a], required: yes please}\n",
        "entries:\n  - {target: severity_id, from: [a], mystery: 1}\n",
        "entries:\n  - {target: severity_id, from: [a, 3]}\n",
    ],
)
def test_malformed_table_documents_are_rejected(tmp_path, document):
    (tmp_path / "common.yaml").write_text(document, encoding="utf-8")
    with pytest.raises(MappingTableError):
        load_tables(tmp_path)


def test_yaml_is_only_read_with_safe_load():
    source = Path(tables_module.__file__).read_text(encoding="utf-8")
    assert "yaml.safe_load" in source
    assert "yaml.load" not in source and "yaml.unsafe_load" not in source


# --- 값 읽기 ---


def test_first_present_value_wins_and_blank_or_non_text_values_are_skipped():
    table = table_of([{"target": "finding_info.title", "from": ["a", "b", "c"]}])
    hit = {"_source": {"a": "  ", "b": 7, "c": "found"}}
    assert apply_table(table, hit).values == {"finding_info.title": "found"}


def test_flat_dotted_key_wins_over_nested_path():
    table = table_of([{"target": "finding_info.title", "from": ["kibana.alert.rule.name"]}])
    flat = {
        "_source": {"kibana.alert.rule.name": "flat", "kibana": {"alert": {"rule": {"name": "n"}}}}
    }
    nested = {"_source": {"kibana": {"alert": {"rule": {"name": "nested"}}}}}
    assert apply_table(table, flat).values["finding_info.title"] == "flat"
    assert apply_table(table, nested).values["finding_info.title"] == "nested"


def test_dollar_prefix_reads_outside_source():
    table = table_of([{"target": "finding_info.uid", "from": ["kibana.alert.uuid", "$._id"]}])
    assert apply_table(table, {"_id": "hit-id", "_source": {}}).values == {
        "finding_info.uid": "hit-id"
    }
    own = {"_id": "hit-id", "_source": {"kibana.alert.uuid": "own"}}
    assert apply_table(table, own).values == {"finding_info.uid": "own"}


def test_missing_required_is_listed_in_table_order_and_optional_is_not():
    table = table_of(
        [
            {"target": "finding_info.analytic.uid", "from": ["x"], "required": True},
            {"target": "finding_info.desc", "from": ["y"]},
            {"target": "severity_id", "from": ["z"], "transform": "severity", "required": True},
        ]
    )
    applied = apply_table(table, {"_source": {"z": "unheard-of"}})
    assert applied.missing == ["finding_info.analytic.uid", "severity_id"]
    assert applied.values == {}


def test_present_but_unreadable_value_does_not_fall_through_to_next_path():
    table = table_of([{"target": "time", "from": ["first", "second"], "transform": "time"}])
    hit = {"_source": {"first": "not-a-time", "second": "2026-11-13T01:00:00Z"}}
    applied = apply_table(table, hit)
    assert applied.values == {}
    assert applied.errors == ["time"]


def test_transforms_convert_values():
    table = table_of(
        [
            {"target": "time", "from": ["t"], "transform": "time"},
            {"target": "severity_id", "from": ["s"], "transform": "severity"},
            {"target": "risk_score", "from": ["r"], "transform": "round_int"},
        ]
    )
    hit = {"_source": {"t": "2026-11-13T01:00:00.000Z", "s": "high", "r": 72.6}}
    expected_time = to_epoch_ms(datetime.fromisoformat("2026-11-13T01:00:00+00:00"))
    assert apply_table(table, hit).values == {
        "time": expected_time,
        "severity_id": 4,
        "risk_score": 73,
    }


@pytest.mark.parametrize(
    ("value", "expected"), [(72.6, 73), (5, 5), (True, None), ("7", None), (float("inf"), None)]
)
def test_round_int_only_accepts_finite_numbers(value, expected):
    table = table_of([{"target": "risk_score", "from": ["r"], "transform": "round_int"}])
    assert apply_table(table, {"_source": {"r": value}}).values.get("risk_score") == expected


def test_registered_transforms_declare_values_for_enum_checks():
    assert TRANSFORMS["severity"].values == frozenset({"2", "3", "4", "5"})
    assert set(TRANSFORMS) >= {"time", "severity", "round_int"}


# --- detect ---


def test_detect_matches_first_condition_that_holds_in_table_order(tmp_path):
    tables = load_tables(table_dir(tmp_path, "source_ok", "source_exists"))
    suricata = {"_source": {"kibana.alert.original_event.module": "suricata"}}
    guardduty = {"_source": {"guardduty": {"description": "d"}}}
    assert matching_source(tables, suricata) == "ok"
    assert matching_source(tables, guardduty) == "exists"
    assert matching_source(tables, {"_source": {"event": {"module": "other"}}}) is None


def test_detect_exists_ignores_null_values(tmp_path):
    tables = load_tables(table_dir(tmp_path, "source_exists"))
    assert matching_source(tables, {"_source": {"guardduty": None}}) is None


# --- 검증기 ---


def test_repository_tables_pass_the_checker():
    assert check_tables(load_tables()) == []


def test_common_alone_covers_required_fields_of_class_2004():
    only_common = {"common": load_tables()["common"]}
    assert check_tables(only_common) == []


def test_checker_accepts_a_source_table_with_array_targets(tmp_path):
    assert check_tables(load_tables(table_dir(tmp_path, "source_ok"))) == []


def test_checker_rejects_a_target_missing_from_the_schema(tmp_path):
    problems = check_tables(load_tables(table_dir(tmp_path, "source_unknown_target")))
    assert problems == ["unknown_target [unknown_target] finding_info.analytic.nope"]


def test_checker_rejects_values_outside_the_target_enum(tmp_path):
    problems = check_tables(load_tables(table_dir(tmp_path, "source_bad_enum")))
    assert len(problems) == 1
    assert problems[0].startswith("bad_enum [bad_enum] activity_id")
    assert "4" in problems[0] and "5" in problems[0]


@pytest.mark.parametrize("dropped", ["severity_id", "finding_info.uid", "time"])
def test_checker_rejects_a_table_set_that_leaves_required_fields_unfilled(tmp_path, dropped):
    common = real_common()
    common["entries"] = [e for e in common["entries"] if e["target"] != dropped]
    problems = check_tables(load_tables(table_dir(tmp_path, common=common)))
    assert any(p.startswith("missing_required") and dropped in p for p in problems)


def test_checker_requires_children_of_a_present_object_only(tmp_path):
    # analytic 항목이 없어도 통과한다. 그 자식의 필수(type_id)는 코드 채움 목록이 맡는다
    common = real_common()
    common["entries"] = [
        e for e in common["entries"] if not e["target"].startswith("finding_info.analytic")
    ]
    assert check_tables(load_tables(table_dir(tmp_path, common=common))) == []


# --- 시작 시점 ---


def bad_tables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tables_module, "TABLE_DIR", table_dir(tmp_path, "source_unknown_transform"))


def test_run_reads_tables_before_claiming_any_raw_record(monkeypatch, tmp_path):
    bad_tables(monkeypatch, tmp_path)

    def claim(*args: Any) -> list[Any]:
        raise AssertionError("표를 읽기 전에 원본을 맡았다")

    monkeypatch.setattr(run_module, "claim_pending_batch", claim)
    settings = Settings(1, 1, 1, 1)
    with pytest.raises(MappingTableError):
        run_module.run(settings, None, "owner")  # type: ignore[arg-type]


def test_cli_exits_with_2_when_a_table_is_wrong(monkeypatch, tmp_path, capsys):
    bad_tables(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    assert main() == 2
    assert "shell" in capsys.readouterr().err
