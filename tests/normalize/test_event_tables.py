"""이벤트 요약 정의(mapping_tables/events/)를 읽고 검사한다(#347, D-068)."""

from pathlib import Path

import pytest

from soc.normalize.event_tables import (
    EVENT_CLASSES,
    check_event_summaries,
    load_event_summaries,
    summary_text,
)
from soc.normalize.tables import MappingTableError, load_tables

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
    assert "events" not in names


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
