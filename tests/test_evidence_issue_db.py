"""근거 발급의 트랜잭션과 중복 방지를 임시 DB에서 확인한다(db 마커, #382).

핵심은 셋이다. 한 문서가 raw_records·normalize_status·events 셋으로 한 번에 들어가는지,
같은 문서를 두 번 발급하지 않는지, 정규화기가 이 원본을 집어가 Event를 또 만들지 않는지다.
가져오기는 가짜 함수로 대신한다(ELK 없음).
"""

import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl

from soc.api import ui_read as read
from soc.api.ui_models import RawDetail
from soc.db.migrate import migrate
from soc.evidence import issue
from soc.ids import siem_ref_key
from soc.tools.registry import ToolError

pytestmark = pytest.mark.db

INDEX = ".ds-logs-nginx.access-default-2026.11.04-000001"
NOW = 1_793_750_400_000
PROFILE = "elk-evidence"
SIEM: dict[str, Any] = {}


@pytest.fixture
def conn(temp_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def document(doc_id: str = "aaa1", **source: Any) -> dict[str, Any]:
    base = {"@timestamp": "2026-11-04T00:00:01Z", "event": {"dataset": "suricata.eve"}}
    return {"_index": INDEX, "_id": doc_id, "_source": {**base, **source}}


def fetcher(*documents: dict[str, Any]):
    by_id = {doc["_id"]: doc for doc in documents}

    def fetch(_siem: Any, index: str, doc_id: str) -> dict[str, Any]:
        assert index == INDEX
        found = by_id.get(doc_id)
        if found is None:
            raise ToolError("failed", reason="not_found")
        return found

    return fetch


def refs(*doc_ids: str) -> dict[str, tuple[str, str]]:
    return {siem_ref_key(f"{INDEX}/{i}"): (INDEX, i) for i in doc_ids}


def run(conn: psycopg.Connection, docs: tuple[dict[str, Any], ...], *doc_ids: str) -> Any:
    return issue(
        conn,
        refs(*doc_ids),
        siem_config=SIEM,
        siem_profile=PROFILE,
        now_ms=NOW,
        fetch=fetcher(*docs),
    )


def counts(conn: psycopg.Connection) -> tuple[int, int, int]:
    return tuple(  # type: ignore[return-value]
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("raw_records", "normalize_status", "events")
    )


def test_one_document_becomes_three_rows(conn: psycopg.Connection) -> None:
    doc = document(source={"ip": "198.51.100.7"})
    result = run(conn, (doc,), "aaa1")

    [(ref, event_id)] = result.evidence_ids.items()
    assert ref == siem_ref_key(f"{INDEX}/aaa1")
    assert event_id.startswith("evt_")
    assert result.dropped == 0
    assert counts(conn) == (1, 1, 1)

    raw = conn.execute(
        "SELECT kind, siem_profile, siem_ref, original_text FROM raw_records"
    ).fetchone()
    assert raw[0] == "event" and raw[1] == PROFILE and raw[2] == ref
    assert json.loads(raw[3]) == doc

    status = conn.execute(
        "SELECT status, result_kind, result_id, source FROM normalize_status"
    ).fetchone()
    assert status == ("succeeded", "event", event_id, "issued")

    event = conn.execute("SELECT ocsf_class, summary, entities FROM events").fetchone()
    assert event[0] == 0
    assert event[1] == "suricata.eve"
    assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in event[2]


def test_the_normalizer_does_not_make_a_second_event_from_the_issued_original(
    conn: psycopg.Connection,
) -> None:
    # normalize_status 행이 없으면 soc.normalize.store가 이 원본을 pending으로 집어간다
    run(conn, (document(),), "aaa1")
    pending = conn.execute(
        "SELECT count(*) FROM raw_records r LEFT JOIN normalize_status s ON s.raw_id = r.id"
        " WHERE s.raw_id IS NULL OR s.status = 'pending'"
    ).fetchone()[0]
    assert pending == 0


def test_the_same_document_is_issued_once(conn: psycopg.Connection) -> None:
    doc = document()
    first = run(conn, (doc,), "aaa1")
    second = run(conn, (doc,), "aaa1")

    assert second.evidence_ids == first.evidence_ids  # 같은 evt_ ID를 다시 준다
    assert second.dropped == 0
    assert counts(conn) == (1, 1, 1)


def test_an_ingested_copy_of_the_same_document_does_not_block_issuing(
    conn: psycopg.Connection,
) -> None:
    # 수집과 프로필이 다르므로 (siem_profile, siem_ref) 유니크에 걸리지 않는다
    ref = siem_ref_key(f"{INDEX}/aaa1")
    conn.execute(
        "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
        " VALUES ('raw_01a19f93-1150-7000-8000-00000000ee01', 'event', 'elk-default', %s,"
        " now(), '{}')",
        (ref,),
    )
    result = run(conn, (document(),), "aaa1")

    assert list(result.evidence_ids) == [ref]
    assert counts(conn) == (2, 1, 1)


def test_a_document_that_cannot_be_fetched_is_dropped_and_the_rest_continue(
    conn: psycopg.Connection,
) -> None:
    good = document("aaa1")
    result = run(conn, (good,), "aaa1", "gone")

    assert list(result.evidence_ids) == [siem_ref_key(f"{INDEX}/aaa1")]
    assert result.dropped == 1
    assert counts(conn) == (1, 1, 1)


def test_a_document_without_a_readable_time_is_dropped(conn: psycopg.Connection) -> None:
    bad = document("bad")
    bad["_source"]["@timestamp"] = "어제"
    result = run(conn, (bad,), "bad")

    assert result.evidence_ids == {}
    assert result.dropped == 1
    assert counts(conn) == (0, 0, 0)


def test_nothing_is_written_when_there_is_nothing_to_issue(conn: psycopg.Connection) -> None:
    result = issue(conn, {}, siem_config=SIEM, siem_profile=PROFILE, now_ms=NOW, fetch=fetcher())
    assert result.evidence_ids == {} and result.dropped == 0
    assert counts(conn) == (0, 0, 0)


def test_the_issued_event_can_be_read_back_as_a_contract(conn: psycopg.Connection) -> None:
    from soc.contracts import validate_contract
    from soc.contracts.event import assemble_event

    run(conn, (document(),), "aaa1")
    row = conn.execute(
        "SELECT id, raw_id, summary, entities, assets, ocsf, details FROM events"
    ).fetchone()
    columns = ("id", "raw_id", "summary", "entities", "assets", "ocsf", "details")
    event = dict(zip(columns, row, strict=True))
    validate_contract("event", assemble_event(event))


def test_l3_hunting_reads_the_entities_of_an_issued_event(conn: psycopg.Connection) -> None:
    """발급한 Event의 엔티티를 record_entities가 읽는다(#382 완료 기준).

    이벤트 매핑표를 없애면서 ECS 공통 엔티티 규칙 하나만 남겼다. 그 규칙이 채운 값을
    L3 헌팅이 읽어 Hunt 엔티티에 머지한다. 빈 배열이면 model_only_entities만 남는다.
    """
    from soc.l3.hunt.store import record_entities

    doc = document(source={"ip": "198.51.100.7"}, user={"name": "svc-backup"})
    result = run(conn, (doc,), "aaa1")
    [event_id] = result.evidence_ids.values()

    entities, missing = record_entities(conn, [event_id])

    assert missing == 0
    assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in entities
    assert {"type": "user", "value": "svc-backup", "role": "actor"} in entities


def test_the_raw_view_shows_an_issued_evidence(
    temp_database: HiddenUrl, conn: psycopg.Connection
) -> None:
    """원본 보기(API)가 발급한 근거를 raw_id와 evt_ID 둘 다로 읽고 응답 모양을 지킨다."""
    doc = document(source={"ip": "198.51.100.7"})
    [(ref, event_id)] = run(conn, (doc,), "aaa1").evidence_ids.items()
    raw_id = conn.execute("SELECT id FROM raw_records").fetchone()[0]

    with psycopg.connect(temp_database, row_factory=psycopg.rows.dict_row) as api:
        by_raw = read.raw_detail(api, "event", raw_id)
        by_event = read.raw_detail(api, "event", event_id)
        page = read.raw_page(api, "event", None, None, 10)

    assert by_raw == by_event
    RawDetail.model_validate(by_event)  # 응답 모델(생성 타입과 같은 계약)을 지킨다
    assert by_event["normalize_status"] == "succeeded" and by_event["error_code"] is None
    assert by_event["seed_source"] is None
    # 수집 원본: 발급한 문서 그대로. siem_ref에 인덱스 이름이 들어 있다
    raw = by_event["raw_record"]
    assert raw["kind"] == "event" and raw["siem_profile"] == PROFILE and raw["siem_ref"] == ref
    assert json.loads(raw["original_text"]) == doc
    # 정규화 결과: class 0 원문 포인터 Event
    record = by_event["record"]
    assert record["details"]["id"] == event_id and record["class_uid"] == 0
    # 목록에도 한 건으로 나온다
    assert [(i["raw_id"], i["record_id"]) for i in page["items"]] == [(raw_id, event_id)]
