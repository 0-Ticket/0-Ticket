"""이벤트 정규화 품질(outcome·source·사유, #351)을 손으로 만든 샘플로 확인한다."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from soc.ids import new_id
from soc.normalize import mapping
from soc.normalize.errors import (
    EVENT_FALLBACK_REASONS,
    EVENT_PARTIAL_REASONS,
    NormalizeError,
)
from soc.normalize.event_tables import load_event_tables
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.tables import MappingTableError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "normalize"
CASES = {
    case["case"]: case
    for case in json.loads((FIXTURES / "raw.json").read_text(encoding="utf-8"))
    if case["kind"] == "event"
}
FALLBACK_TIME_CODE = "missing_request_time_used_at_timestamp"


def sample(name: str) -> RawRow:
    return RawRow(
        id=new_id("raw"),
        kind="event",
        original=json.loads((FIXTURES / "events" / f"{name}.json").read_text(encoding="utf-8")),
    )


def case(name: str) -> RawRow:
    original = json.loads(json.dumps(CASES[name]["original"]))
    return RawRow(id=new_id("raw"), kind="event", original=original)


def quality(raw: RawRow) -> tuple[Any, ...]:
    result = normalize(raw)
    return result.outcome, result.source, result.error_code, result.missing_fields


def test_nginx_sample_is_ok_with_table_source_name() -> None:
    assert quality(sample("nginx")) == ("ok", "nginx", None, ())


@pytest.mark.parametrize("status", [None, "abc"])
def test_nginx_optional_status_code_is_omitted_and_stays_ok(status: str | None) -> None:
    raw = sample("nginx")
    response = raw.original["_source"]["http"]["response"]
    if status is None:
        del response["status_code"]
    else:
        response["status_code"] = status

    result = normalize(raw)

    assert "code" not in result.row["ocsf"]["http_response"]
    assert (result.outcome, result.error_code, result.missing_fields) == ("ok", None, ())


def test_modsecurity_with_request_time_is_ok() -> None:
    assert quality(sample("modsecurity")) == ("ok", "modsecurity", None, ())


def test_modsecurity_without_request_time_uses_at_timestamp_as_partial() -> None:
    raw = sample("modsecurity")
    del raw.original["_source"]["transaction"]["time_stamp"]

    result = normalize(raw)

    assert (result.outcome, result.source) == ("partial", "modsecurity")
    assert result.error_code == FALLBACK_TIME_CODE
    assert result.missing_fields == ("metadata.original_time",)
    assert result.row["ocsf"]["time"] == 1795103401000  # @timestamp 2026-11-19T15:50:01Z
    assert "original_time" not in result.row["ocsf"]["metadata"]


@pytest.mark.parametrize("invalid", ["invalid", "", None])
def test_modsecurity_unreadable_request_time_fails(invalid: str | None) -> None:
    raw = sample("modsecurity")
    raw.original["_source"]["transaction"]["time_stamp"] = invalid

    with pytest.raises(NormalizeError) as raised:
        normalize(raw)

    assert raised.value.code == "validation_failed"


def test_modsecurity_without_any_time_fails() -> None:
    raw = sample("modsecurity")
    del raw.original["_source"]["transaction"]["time_stamp"]
    del raw.original["_source"]["@timestamp"]

    with pytest.raises(NormalizeError) as raised:
        normalize(raw)

    assert raised.value.code == "validation_failed"


def test_index_rule_events_use_class_names_as_source() -> None:
    assert quality(case("web_nested_fields")) == ("ok", "class_4002", None, ())
    assert quality(case("cloud_read_call")) == ("ok", "class_6003", None, ())


def test_event_without_supported_mapping_is_a_base_event_fallback() -> None:
    raw = case("event_without_supported_class")

    result = normalize(raw)

    assert result.row["ocsf"]["class_uid"] == 0
    assert (result.outcome, result.source) == ("fallback", "unknown")
    assert result.error_code == "unsupported_event_mapping"
    assert result.missing_fields == ()


def test_a_required_value_that_a_table_cannot_get_makes_the_event_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tables = load_event_tables()
    http = tables.classes[4002]
    required = tuple(
        replace(entry, required=True) if entry.target == "http_response.code" else entry
        for entry in http.entries
    )
    patched = replace(tables, classes={**tables.classes, 4002: replace(http, entries=required)})
    monkeypatch.setattr(mapping, "load_event_tables", lambda: patched)
    raw = sample("nginx")
    raw.original["_source"]["http"]["response"]["status_code"] = "abc"

    result = normalize(raw)

    assert (result.outcome, result.error_code) == ("partial", None)
    assert result.missing_fields == ("http_response.code",)


def test_event_reason_codes_are_listed_separately() -> None:
    assert EVENT_PARTIAL_REASONS == (FALLBACK_TIME_CODE,)
    assert EVENT_FALLBACK_REASONS == ("unsupported_event_mapping",)


def test_event_source_table_names_must_be_safe_identifiers(tmp_path: Path) -> None:
    from soc.normalize.event_tables import load_event_tables as load

    (tmp_path / "4002.yaml").write_text(
        "class_uid: 4002\nsummary: [activity_name]\nentries: []\n", encoding="utf-8"
    )
    (tmp_path / "Bad-Name.yaml").write_text(
        "class_uid: 4002\ndetect:\n  - field: [event.module]\n    equals: x\n", encoding="utf-8"
    )

    with pytest.raises(MappingTableError):
        load(tmp_path)
