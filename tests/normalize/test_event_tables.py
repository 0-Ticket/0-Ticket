"""이벤트 요약 정의(mapping_tables/events/)를 읽고 검사한다(#347, D-068)."""

from pathlib import Path

import pytest

from soc.normalize.event_tables import (
    EVENT_CLASSES,
    check_event_summaries,
    load_event_summaries,
    load_event_tables,
    summary_text,
)
from soc.normalize.table_check import check_event_tables
from soc.normalize.tables import MappingTableError, load_tables, matching_source

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize" / "event_tables"


def test_the_seven_stored_classes_are_all_defined() -> None:
    assert (
        set(load_event_summaries()) == set(EVENT_CLASSES) == {0, 2003, 3002, 4001, 4002, 4003, 6003}
    )


def test_every_summary_path_exists_in_the_class_definition() -> None:
    assert check_event_summaries(load_event_summaries()) == []


def test_alert_table_loader_does_not_read_the_events_folder() -> None:
    names = set(load_tables())

    assert names.isdisjoint({str(n) for n in EVENT_CLASSES})
    assert names.isdisjoint({"events", "nginx"})


@pytest.mark.parametrize(
    ("class_uid", "ocsf", "expected"),
    [
        (
            4002,
            {
                "http_request": {"http_method": "GET", "url": {"path": "/api", "url_string": "/x"}},
                "http_response": {"code": 200},
            },
            "GET /api 200",
        ),
        (4002, {"activity_name": "BREW", "http_request": {"url": {"url_string": "/x"}}}, "BREW /x"),
        (
            6003,
            {"api": {"operation": "GetObject"}, "actor": {"user": {"name": "ops"}}},
            "GetObject ops",
        ),
        (0, {"activity_name": "logon"}, "logon"),
        (
            3002,
            {"user": {"name": "kim"}, "activity_name": "Logon", "status": "Success"},
            "kim Logon Success",
        ),
        (4003, {"query": {"hostname": "a.example.com", "type": "A"}}, "a.example.com A"),
        (
            4001,
            {"connection_info": {"protocol_name": "tcp"}, "src_endpoint": {"ip": "192.0.2.1"}},
            "tcp 192.0.2.1",
        ),
        (2003, {"finding_info": {"title": "버킷이 공개됨"}}, "버킷이 공개됨"),
        (4002, {"http_response": {"code": True}}, None),
        (4002, {"http_response": {"code": 404.0}}, "404"),
        (4002, {"http_response": {"code": 404.5}}, "404.5"),
        (4002, {"http_response": {"code": float("nan")}}, None),
        (4002, {"http_response": {"code": float("inf")}}, None),
        (4002, {"http_response": {"code": [404]}}, None),
        (4002, {"http_response": {"code": " "}}, None),
        (0, {}, None),
    ],
)
def test_summary_text_joins_the_values_that_exist(class_uid, ocsf, expected) -> None:
    assert summary_text(class_uid, ocsf) == expected


def test_unknown_class_has_no_summary() -> None:
    assert summary_text(1007, {"activity_name": "x"}) is None


def test_bad_tables_are_rejected_with_the_file_name() -> None:
    for name in ("bad_name_mismatch", "bad_unknown_key", "bad_empty_summary", "bad_cell_type"):
        with pytest.raises(MappingTableError, match=r"^4002\.yaml: "):
            load_event_summaries(FIXTURES / name)


def test_unknown_path_is_reported() -> None:
    problems = check_event_summaries(load_event_summaries(FIXTURES / "unknown_path"))

    assert "unknown_path [4002] http_request.no_such_field" in problems
    assert "missing_class [0]" in problems


def test_source_tables_load_in_name_order_and_keep_class_summaries(tmp_path: Path) -> None:
    (tmp_path / "4002.yaml").write_text("class_uid: 4002\nsummary: [time]\n")
    for name in ("z_source", "a_source"):
        (tmp_path / f"{name}.yaml").write_text(
            "class_uid: 4002\ndetect: [{field: event.module, exists: true}]\nentries: []\n"
        )

    tables = load_event_tables(tmp_path)
    assert matching_source(tables.sources, {"_source": {"event.module": "sample"}}) == "a_source"
    assert tables.source_classes == {"a_source": 4002, "z_source": 4002}
    assert tables.classes[4002].name == "4002"
    assert set(load_event_summaries(tmp_path)) == {4002}


@pytest.mark.parametrize(
    ("filename", "document", "problem"),
    [
        ("2004.yaml", "class_uid: 2004\nsummary: [time]\n", "class_uid"),
        ("0.yaml", "class_uid: false\nsummary: [time]\n", "class_uid"),
        ("bad.yaml", "class_uid: 4002\nentries: []\nunknown: true\n", "알 수 없는 키"),
        ("bad.yaml", "class_uid: 4002\nentries: []\ndetect: [{}]\n", "field"),
        ("bad.yaml", "class_uid: 4002\nentries: []\n", "detect"),
        ("bad.yaml", "class_uid: 2004\nentries: []\n", "class_uid"),
        (
            "bad.yaml",
            "class_uid: 6003\nentries: []\ndetect: [ {field: x, exists: true} ]\n",
            "6003",
        ),
    ],
)
def test_invalid_event_tables_report_the_file_name(tmp_path, filename, document, problem) -> None:
    (tmp_path / "4002.yaml").write_text("class_uid: 4002\nsummary: [time]\n")
    (tmp_path / filename).write_text(document)

    with pytest.raises(MappingTableError, match=rf"^{filename}: .*{problem}"):
        load_event_tables(tmp_path)


def test_event_table_targets_required_paths_enums_and_ecs_are_valid() -> None:
    assert check_event_tables(load_event_tables()) == []


def test_checker_reports_bad_targets_required_paths_enums_and_ecs_paths(tmp_path: Path) -> None:
    (tmp_path / "4002.yaml").write_text(
        "class_uid: 4002\nsummary: [time]\n"
        "entries:\n"
        "  - {target: unknown_target, from: [url.path, unknown.entry]}\n"
        "  - {target: http_request.http_method, from: [network.transport], transform: severity}\n"
        "entities:\n"
        "  - {type: domain, from: [url.domain, unknown.entity]}\n"
    )
    (tmp_path / "sample.yaml").write_text(
        "class_uid: 4002\ndetect: [{field: event.module, equals: sample}]\n"
        "entries: [{target: time, from: [source_specific.time]}]\n"
    )

    problems = check_event_tables(load_event_tables(tmp_path))

    assert "unknown_target [4002] unknown_target" in problems
    assert any(
        problem.startswith("bad_enum [4002] http_request.http_method:") for problem in problems
    )
    assert "missing_required [4002] time" in problems
    assert "missing_required [4002+sample] time" not in problems
    assert "unknown_ecs_field [4002] unknown.entry" in problems
    assert "unknown_ecs_field [4002] unknown.entity" in problems
    assert all("source_specific.time" not in problem for problem in problems)
