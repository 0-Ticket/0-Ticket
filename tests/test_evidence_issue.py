"""근거 발급의 행 만들기(#382, D-085). DB 없이 순수 함수만 본다.

트랜잭션과 중복 방지는 tests/test_evidence_issue_db.py의 db 마커 테스트가 본다.
샘플은 손으로 만들고 IP는 문서용 대역, 도메인은 example.com을 쓴다(docs/security.md).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from soc.agent.config import load_config
from soc.contracts import validate_contract
from soc.contracts.event import assemble_event, event_summary
from soc.evidence import evidence_ocsf, evidence_rows
from soc.ids import siem_ref_key

REPO = Path(__file__).resolve().parents[1]
INDEX = ".ds-logs-nginx.access-default-2026.11.04-000001"
NOW = 1_793_750_400_000  # 2026-11-04T00:00:00Z
PROFILE = "elk-evidence"


def document(**source: Any) -> dict[str, Any]:
    base = {"@timestamp": "2026-11-04T00:00:01Z"}
    return {"_index": INDEX, "_id": "aaa1", "_source": {**base, **source}}


def rows(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    made = evidence_rows(doc, siem_profile=PROFILE, now_ms=NOW)
    assert made is not None
    return made


# 원문 행


def test_the_raw_row_keeps_the_document_whole_and_unchanged() -> None:
    doc = document(event={"module": "suricata"}, message="a" * 2000)
    raw, _ = rows(doc)

    assert json.loads(raw["original_text"]) == doc
    assert raw["kind"] == "event"
    assert raw["siem_profile"] == PROFILE
    assert raw["fetched_at"] == NOW
    validate_contract("raw_record", raw)


def test_the_stored_key_matches_what_ingest_would_write() -> None:
    raw, _ = rows(document())
    assert raw["siem_ref"] == siem_ref_key(f"{INDEX}/aaa1")


def test_an_odd_document_id_is_escaped_in_the_stored_key() -> None:
    doc = document()
    doc["_id"] = 'q"b\\s\x01z한글'
    raw, _ = rows(doc)

    assert raw["siem_ref"] == siem_ref_key(f"{INDEX}/{doc['_id']}")
    assert raw["siem_ref"].isascii()


# Event 행


def test_the_event_is_a_class_zero_pointer_without_the_original() -> None:
    _, event = rows(document(event={"dataset": "suricata.eve"}, message="payload"))

    assert event["ocsf_class"] == 0
    assert event["ocsf"]["class_uid"] == 0
    # 원문은 raw_records에만 있다(D-059·D-008). get_raw가 돌려준다
    assert "raw_data" not in event["ocsf"]
    assert "payload" not in json.dumps(event["ocsf"], ensure_ascii=False)
    validate_contract("event", assemble_event(event))


def test_the_summary_comes_from_event_dataset() -> None:
    _, event = rows(document(event={"module": "suricata", "dataset": "suricata.eve"}))
    assert event["summary"] == "suricata.eve"
    assert event_summary(assemble_event(event)) == "suricata.eve"


def test_event_module_is_used_when_there_is_no_dataset() -> None:
    _, event = rows(document(event={"module": "modsecurity"}))
    assert event["summary"] == "modsecurity"


def test_flat_dotted_event_fields_are_read_too() -> None:
    # 소스에 따라 event를 객체가 아니라 점 이름의 평면 칸으로 둔다
    _, event = rows(document(**{"event.dataset": "nginx.access"}))
    assert event["summary"] == "nginx.access"


def test_the_summary_is_never_empty() -> None:
    # 계약이 공백 아닌 글자 하나를 요구한다
    for source in ({}, {"event": {}}, {"event": {"dataset": "   "}}, {"event": "nope"}):
        _, event = rows(document(**source))
        assert event["summary"].strip(), source
        validate_contract("event", assemble_event(event))


def test_severity_is_unknown_because_nothing_judged_it() -> None:
    _, event = rows(document())
    assert event["ocsf"]["severity_id"] == 0


# 엔티티: 매핑표를 없애도 ECS 공통 규칙 하나는 남는다


def test_ecs_common_entities_are_filled_so_l3_hunting_keeps_working() -> None:
    # src/soc/l3/hunt/store.py의 record_entities가 이 값을 읽어 헌팅 엔티티에 머지한다
    _, event = rows(
        document(
            source={"ip": "198.51.100.7"},
            destination={"ip": "192.0.2.22"},
            user={"name": "svc-backup"},
        )
    )

    assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in event["entities"]
    assert {"type": "ip", "value": "192.0.2.22", "role": "dst"} in event["entities"]
    assert {"type": "user", "value": "svc-backup", "role": "actor"} in event["entities"]


def test_a_document_with_no_ecs_entity_fields_gets_an_empty_list() -> None:
    _, event = rows(document(event={"dataset": "suricata.eve"}))
    assert event["entities"] == []


def test_the_collector_host_is_not_an_entity() -> None:
    # 센서 값은 엔티티로 만들지 않는다(D-059)
    _, event = rows(document(host={"name": "a5da1a46dfa5"}, agent={"name": "filebeat"}))
    assert event["entities"] == []


# 시각


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-04T00:00:01Z", NOW + 1000),
        ("2026-11-04T00:00:01+00:00", NOW + 1000),
        ("2026-11-04T09:00:01+09:00", NOW + 1000),
        ("2026-11-04T00:00:01", NOW + 1000),  # 시간대가 없으면 UTC로 본다
        (NOW + 5, NOW + 5),
    ],
)
def test_the_event_time_is_the_source_timestamp(value: Any, expected: int) -> None:
    doc = document()
    doc["_source"]["@timestamp"] = value
    _, event = rows(doc)
    assert event["time"] == expected


@pytest.mark.parametrize("value", [None, "", "어제", True, [], {}, "2026-13-45T99:00:00Z"])
def test_an_unreadable_timestamp_is_not_issued(value: Any) -> None:
    doc = document()
    doc["_source"]["@timestamp"] = value
    assert evidence_rows(doc, siem_profile=PROFILE, now_ms=NOW) is None


@pytest.mark.parametrize(
    "doc",
    [
        {"_index": INDEX, "_id": "a"},  # _source 없음
        {"_index": INDEX, "_id": "a", "_source": "nope"},
        {"_id": "a", "_source": {}},  # _index 없음
        {"_index": INDEX, "_source": {}},  # _id 없음
    ],
)
def test_a_document_of_the_wrong_shape_is_not_issued(doc: dict[str, Any]) -> None:
    assert evidence_rows(doc, siem_profile=PROFILE, now_ms=NOW) is None


# OCSF 문서


def test_the_ocsf_document_has_no_source_specific_fields() -> None:
    ocsf = evidence_ocsf(document(suricata={"eve": {"signature_id": 2001}}), NOW)
    assert set(ocsf) == {"class_uid", "time", "severity_id", "message", "metadata"}


# 설정


def test_the_issued_profile_is_separate_from_ingest() -> None:
    import tomllib

    raw = (REPO / "config" / "default.toml").read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    issued = config["tools"]["siem"]["evidence_siem_profile"]
    # 수집 체크포인트와 섞이지 않게 다른 값이어야 한다
    assert issued and issued != config["ingest"]["siem_profile"]
    assert load_config(REPO / "config")["tools"]["siem"]["evidence_siem_profile"] == issued
