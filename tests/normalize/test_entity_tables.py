"""매핑표의 엔티티 선언과 detect 목록 field(#332)를 확인한다.

테스트용 표는 tests/fixtures/normalize/mapping_tables/에 있다.
"""

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest

from soc.ids import new_id
from soc.normalize import tables as tables_module
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.table_check import check_tables
from soc.normalize.tables import (
    MappingTableError,
    apply_entities,
    load_tables,
    matching_source,
    parse_table,
)
from soc.normalize.transforms import ENTITY_TRANSFORMS

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize" / "mapping_tables"
REAL_DIR = Path(tables_module.__file__).parent / "mapping_tables"


def table_dir(tmp_path: Path, *fixtures: str) -> Path:
    """실제 common 표와 테스트용 소스 표를 한 폴더에 모은다."""
    shutil.copy(REAL_DIR / "common.yaml", tmp_path / "common.yaml")
    for name in fixtures:
        shutil.copy(FIXTURES / f"{name}.yaml", tmp_path / f"{name.removeprefix('source_')}.yaml")
    return tmp_path


def table_of(entities: list[dict[str, Any]]):
    """엔티티 목록으로 표를 만든다(로더를 거친다)."""
    return parse_table("t", {"entries": [], "entities": entities})


def triples(applied) -> list[tuple[str, str, str | None]]:
    return [(e["type"], e["value"], e["role"]) for e in applied.entities]


def alert(source: dict[str, Any]) -> RawRow:
    """_source만 바꿔 쓰는 최소 알럿 원본."""
    base = {
        "kibana.alert.uuid": "u-1",
        "kibana.alert.start": "2026-11-13T00:00:00.000Z",
        "kibana.alert.original_time": "2026-11-12T23:59:00.000Z",
        "kibana.alert.rule.name": "rule",
        "kibana.alert.rule.rule_id": "r-1",
        "kibana.alert.severity": "high",
    }
    original = {"_id": "h-1", "_index": "i", "_source": {**base, **copy.deepcopy(source)}}
    return RawRow(id=new_id("raw"), kind="alert", original=original)


# --- 로더 ---


def test_entities_load_with_role_defaulting_to_null(tmp_path):
    table = load_tables(table_dir(tmp_path, "source_entities_ok"))["entities_ok"]
    assert [(e.type, e.role, e.transform) for e in table.entities] == [
        ("ip", "dst", "ip"),
        ("domain", "dst", "domain_or_ip"),
        ("host", None, None),
    ]
    assert table.detect[0].fields == ("event.module", "kibana.alert.original_event.module")


@pytest.mark.parametrize(
    "fixture",
    [
        "source_bad_entity_type",
        "source_bad_entity_role",
        "source_unknown_entity_transform",
        "source_bad_entity_shape",
        "source_bad_detect_list",
    ],
)
def test_bad_entity_declarations_fail_at_load_time(tmp_path, fixture):
    with pytest.raises(MappingTableError):
        load_tables(table_dir(tmp_path, fixture))


def test_unknown_entity_transform_error_names_it(tmp_path):
    with pytest.raises(MappingTableError, match="shell"):
        load_tables(table_dir(tmp_path, "source_unknown_entity_transform"))


def test_entities_must_be_a_list():
    with pytest.raises(MappingTableError):
        parse_table("t", {"entries": [], "entities": {}})


def test_registered_entity_transforms():
    assert set(ENTITY_TRANSFORMS) == {"ip", "domain_or_ip"}


# --- 적용 ---


def test_first_present_value_wins_and_declaration_order_is_kept():
    table = table_of(
        [
            {"type": "user", "role": "actor", "from": ["a", "b"]},
            {"type": "url", "role": "dst", "from": ["u"]},
        ]
    )
    applied = apply_entities(table, {"_source": {"a": " ", "b": "alice", "u": "/x"}})
    assert triples(applied) == [("user", "alice", "actor"), ("url", "/x", "dst")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("www.example.com", ("domain", "www.example.com")),
        ("www.example.com:8443", ("domain", "www.example.com")),
        ("198.51.100.1", ("ip", "198.51.100.1")),
        ("198.51.100.1:8080", ("ip", "198.51.100.1")),
        ("[2001:db8::1]:8443", ("ip", "2001:db8::1")),
        ("2001:db8::1", ("ip", "2001:db8::1")),
    ],
)
def test_domain_or_ip_strips_the_port_and_reclassifies_ips(value, expected):
    table = table_of(
        [{"type": "domain", "role": "dst", "from": ["d"], "transform": "domain_or_ip"}]
    )
    applied = apply_entities(table, {"_source": {"d": value}})
    assert triples(applied) == [(*expected, "dst")]


def test_invalid_ip_is_dropped_and_reported_by_role():
    table = table_of(
        [
            {"type": "ip", "role": "src", "from": ["s"], "transform": "ip"},
            {"type": "ip", "role": "dst", "from": ["d"], "transform": "ip"},
        ]
    )
    applied = apply_entities(table, {"_source": {"s": "999.1.1.1", "d": "not-an-ip"}})
    assert applied.entities == []
    assert applied.missing == ["evidences[].src_endpoint.ip", "evidences[].dst_endpoint.ip"]


def test_entities_without_a_value_are_skipped_silently():
    table = table_of([{"type": "ip", "role": "src", "from": ["s"], "transform": "ip"}])
    applied = apply_entities(table, {"_source": {}})
    assert applied.entities == [] and applied.missing == []


# --- detect ---


def test_detect_field_list_keeps_event_module_priority(tmp_path):
    tables = load_tables(table_dir(tmp_path, "source_entities_ok"))
    only_original = {"_source": {"kibana.alert.original_event.module": "suricata"}}
    both_agree = {"_source": {"event": {"module": "suricata"}}}
    shadowed = {
        "_source": {
            "event": {"module": "nginx"},
            "kibana.alert.original_event.module": "suricata",
        }
    }
    assert matching_source(tables, only_original) == "entities_ok"
    assert matching_source(tables, both_agree) == "entities_ok"
    assert matching_source(tables, shadowed) is None


# --- 저장소의 표 ---


def test_repository_sources_declare_detect_and_modsecurity_adds_destination():
    tables = load_tables()
    assert {"common", "modsecurity", "suricata"} <= set(tables)
    assert tables["suricata"].entities == () and tables["suricata"].detect
    assert [e.sources[0] for e in tables["modsecurity"].entities] == [
        "transaction.client_ip",
        "transaction.host_ip",
        "transaction.request.hostname",
    ]
    assert [e.sources[0] for e in tables["common"].entities] == [
        "source.ip",
        "destination.ip",
        "user.name",
        "url.domain",
        "destination.domain",
        "url.original",
    ]


def test_repository_tables_pass_the_checker_with_entities():
    assert check_tables(load_tables()) == []


# --- 정규화 결과 ---


def entity_triples(row: RawRow) -> list[tuple[str, str, str | None]]:
    result = normalize(row)
    return [(e["type"], e["value"], e["role"]) for e in result.row["entities"]]


def test_modsecurity_destination_reaches_entities_and_observables():
    row = alert(
        {
            "event": {"module": "modsecurity"},
            "source": {"ip": "203.0.113.4"},
            "transaction": {
                "client_ip": "203.0.113.4",
                "host_ip": "192.0.2.3",
                "request": {"hostname": "198.51.100.1"},
            },
        }
    )
    result = normalize(row)
    assert entity_triples(row) == [
        ("ip", "203.0.113.4", "src"),
        ("ip", "192.0.2.3", "dst"),
        ("ip", "198.51.100.1", "dst"),
    ]
    observed = [(o["type_id"], o["value"]) for o in result.row["ocsf"]["observables"]]
    assert observed == [(2, "203.0.113.4"), (2, "192.0.2.3"), (2, "198.51.100.1")]
    assert result.outcome == "ok" and result.source == "modsecurity"


def test_invalid_modsecurity_host_ip_is_listed_as_missing_like_other_invalid_ips():
    row = alert(
        {
            "event": {"module": "modsecurity"},
            "source": {"ip": "203.0.113.4"},
            "transaction": {"host_ip": "not-an-ip"},
        }
    )
    result = normalize(row)
    # 틀린 IP는 outcome을 바꾸지 않고 missing_fields에만 남는다(alert_skeleton invalid_ips 케이스)
    assert result.outcome == "ok"
    assert result.missing_fields == ("evidences[].dst_endpoint.ip",)


def test_same_invalid_ip_path_is_reported_once():
    row = alert(
        {
            "event": {"module": "modsecurity"},
            "source": {"ip": "999.1.1.1"},
            "transaction": {"client_ip": "999.1.1.1"},
        }
    )
    assert normalize(row).missing_fields == ("evidences[].src_endpoint.ip",)


def test_sensor_ids_never_become_entities():
    sensor = "26d0b29d0b9a"
    row = alert(
        {
            "event": {"module": "modsecurity"},
            "host": {"name": sensor},
            "agent": {"name": sensor, "hostname": sensor},
            "source": {"ip": "203.0.113.4"},
            "transaction": {"host_ip": "192.0.2.3"},
        }
    )
    values = [value for _, value, _ in entity_triples(row)]
    assert sensor not in values


def test_source_without_a_table_keeps_the_ecs_entities():
    row = alert({"event": {"module": "nginx"}, "source": {"ip": "198.51.100.7"}})
    result = normalize(row)
    assert result.source == "unknown"
    assert entity_triples(row) == [("ip", "198.51.100.7", "src")]


def test_module_from_original_event_is_used_only_when_event_module_is_missing():
    only_original = alert({"kibana.alert.original_event.module": "suricata"})
    shadowed = alert(
        {"event": {"module": "nginx"}, "kibana.alert.original_event.module": "suricata"}
    )
    assert normalize(only_original).source == "suricata"
    assert normalize(shadowed).source == "unknown"
