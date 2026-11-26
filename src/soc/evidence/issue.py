"""근거 발급(#382, D-083).

이벤트는 OCSF로 정규화하지 않는다. L1·L2·L3가 심 조회 도구로 문서를 찾고 모델이 `siem_refs`에
적으면, 워커가 그 문서를 통째로 가져와 저장하고 `evt_` ID를 발급한다. 모델은 인용만 하고 저장은
코드가 한다 — 도구가 DB에 쓰면 밖에서 온 로그 문장이 쓰기를 유발할 수 있다(`docs/security.md`).

한 문서를 한 트랜잭션에서 셋으로 쓴다.

1. `raw_records`에 원문. `(siem_profile, siem_ref)` 유니크가 중복을 막는다
2. `normalize_status`에 `succeeded`·`result_kind='event'`·`result_id`. 이걸 빼면
   `soc.normalize.store`가 그 원본을 집어가 같은 원본으로 Event를 또 만든다
3. `events`에 class 0 행. `ocsf`는 포인터이고 원문은 `raw_records.original_text`에만 있다
   (D-059·D-008의 원본·결과 분리). 모델은 `get_raw`로 읽는다

실패는 그 근거만 버리고 계속한다. 버린 수만 알리고 `siem_ref` 값은 알리지 않는다(밖에서 온
문자열). 심 장애로 판정 전체가 멈추지 않게 하려는 것이고 `asset_lookup_failed`와 같은 방식이다.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.contracts.event import assemble_event
from soc.ids import SiemRefKey, new_id, siem_ref_key
from soc.ingest.quarantine import serialize_original
from soc.normalize.mapping import event_row
from soc.normalize.tables import COMMON, apply_entities, load_tables
from soc.tools.registry import ToolError
from soc.tools.siem import fetch_document

# 발급한 원본의 normalize_status.source. 이벤트 행은 소문자·숫자·밑줄이어야 한다(0305)
SOURCE = "issued"
# 요약을 만들 값이 하나도 없을 때. soc.contracts.event.EMPTY_SUMMARY와 같은 값이다
FALLBACK_MESSAGE = "event"
# 발급한 근거의 심각도. 정규화가 판단한 값이 아니므로 Unknown이다
SEVERITY_UNKNOWN = 0

Fetch = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Issued:
    """발급 결과.

    Attributes:
        evidence_ids: 저장한 문서의 저장 키 -> 발급한 evt_ ID. 다음 태스크가 인용할 수 있다.
        dropped: 가져오거나 저장하지 못해 버린 근거 수. 값은 남기지 않는다.
    """

    evidence_ids: dict[str, str]
    dropped: int


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _time_ms(source: Mapping[str, Any]) -> int | None:
    """원문의 @timestamp를 epoch 밀리초로. 읽을 수 없으면 None(발급하지 않는다)."""
    value = source.get("@timestamp")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:  # 시간대가 없으면 UTC로 본다
        parsed = parsed.replace(tzinfo=UTC)
    return to_epoch_ms(parsed)


def _message(source: Mapping[str, Any]) -> str:
    """한 줄 요약. event.dataset, 없으면 event.module, 그것도 없으면 "event"다(D-068 폴백).

    계약이 공백 아닌 글자 하나를 요구하므로 빈 문자열이 되지 않는다. 원본은 event를 객체로 두기도
    하고 점 이름의 평면 칸으로 두기도 해서 둘 다 본다.
    """
    event = source.get("event")
    if isinstance(event, Mapping):
        for key in ("dataset", "module"):
            found = _text(event.get(key))
            if found is not None:
                return found
    for key in ("event.dataset", "event.module"):
        found = _text(source.get(key))
        if found is not None:
            return found
    return FALLBACK_MESSAGE


def evidence_ocsf(document: Mapping[str, Any], time_ms: int) -> dict[str, Any]:
    """발급한 근거의 OCSF 문서. Base Event(class 0) 포인터다.

    원문은 넣지 않는다. `raw_records.original_text`에만 두고 `get_raw`가 돌려준다.

    Args:
        document: fetch_document의 결과({_index, _id, _source}).
        time_ms: 활동이 소스에서 발생한 시각(epoch 밀리초).
    """
    raw_source = document.get("_source")
    source = raw_source if isinstance(raw_source, Mapping) else {}
    return {
        "class_uid": 0,
        "time": time_ms,
        "severity_id": SEVERITY_UNKNOWN,
        "message": _message(source),
        "metadata": {"version": "1.9.0", "product": {"name": "siem"}},
    }


def evidence_rows(
    document: Mapping[str, Any], *, siem_profile: str, now_ms: int
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(raw_records 행, events 행). 시각을 읽을 수 없으면 None(발급하지 않는다).

    Args:
        document: fetch_document의 결과.
        siem_profile: 발급분의 프로필. 수집과 분리한 값이다([tools.siem] evidence_siem_profile).
        now_ms: 가져온 시각(epoch 밀리초).
    """
    source = document.get("_source")
    index, doc_id = document.get("_index"), document.get("_id")
    if not isinstance(source, Mapping) or not isinstance(index, str) or not isinstance(doc_id, str):
        return None
    time_ms = _time_ms(source)
    if time_ms is None:
        return None
    raw = {
        "id": new_id("raw"),
        "kind": "event",
        "siem_profile": siem_profile,
        "siem_ref": siem_ref_key(f"{index}/{doc_id}"),
        "fetched_at": now_ms,
        "original_text": serialize_original(dict(document)),
    }
    ocsf = evidence_ocsf(document, time_ms)
    applied = apply_entities(load_tables()[COMMON], dict(document))
    event = event_row(new_id("evt"), raw["id"], ocsf, applied.entities)
    validate_contract("raw_record", raw)
    validate_contract("event", assemble_event(event))
    return raw, event


def issue(
    conn: psycopg.Connection,
    refs: Mapping[str, tuple[str, str]],
    *,
    siem_config: Mapping[str, Any],
    siem_profile: str,
    now_ms: int,
    fetch: Fetch = fetch_document,
) -> Issued:
    """인용된 문서를 가져와 발급한다. 문서 하나가 실패해도 나머지는 계속한다.

    Args:
        conn: autocommit 연결. 문서마다 트랜잭션을 연다.
        refs: AgentResult.cited_siem_refs. 저장 키 -> (_index, _id).
        siem_config: 설정의 [tools.siem].
        siem_profile: 발급분의 프로필(수집과 분리).
        now_ms: 가져온 시각.
        fetch: 원문 가져오기. 테스트가 바꿔 끼운다.
    """
    issued: dict[str, str] = {}
    dropped = 0
    for ref, (index, doc_id) in refs.items():
        existing = _existing(conn, siem_profile, ref)
        if existing is not None:
            issued[ref] = existing
            continue
        try:
            document = fetch(siem_config, index, doc_id)
        except ToolError:
            dropped += 1
            continue
        rows = evidence_rows(document, siem_profile=siem_profile, now_ms=now_ms)
        if rows is None:
            dropped += 1
            continue
        try:
            issued[ref] = _save(conn, *rows)
        except psycopg.Error:
            dropped += 1
    return Issued(issued, dropped)


def _existing(conn: psycopg.Connection, siem_profile: str, ref: str) -> str | None:
    """이미 발급한 문서의 evt_ ID. 없으면 None. 같은 문서를 두 번 발급하지 않는다."""
    row = conn.execute(
        "SELECT s.result_id FROM raw_records r JOIN normalize_status s ON s.raw_id = r.id"
        " WHERE r.siem_profile = %s AND r.siem_ref = %s AND s.result_kind = 'event'"
        " AND s.status = 'succeeded'",
        (siem_profile, SiemRefKey(ref)),
    ).fetchone()
    return row[0] if row else None


def _save(conn: psycopg.Connection, raw: dict[str, Any], event: dict[str, Any]) -> str:
    """원문·정규화 상태·Event를 한 트랜잭션에서 쓴다. 발급한 evt_ ID를 돌려준다."""
    with conn.transaction():
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (
                raw["id"],
                raw["kind"],
                raw["siem_profile"],
                raw["siem_ref"],
                to_datetime(raw["fetched_at"]),
                raw["original_text"],
            ),
        )
        # 이 줄을 빼면 정규화기가 이 원본을 집어가 같은 원본으로 Event를 또 만든다
        conn.execute(
            "INSERT INTO normalize_status (raw_id, status, attempts, last_attempt_at,"
            " result_kind, result_id, source) VALUES (%s, 'succeeded', 1, %s, 'event', %s, %s)",
            (raw["id"], to_datetime(raw["fetched_at"]), event["id"], SOURCE),
        )
        conn.execute(
            "INSERT INTO events (id, raw_id, time, ocsf_class, summary, entities, assets, ocsf,"
            " details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                event["id"],
                event["raw_id"],
                to_datetime(event["time"]),
                event["ocsf_class"],
                event["summary"],
                Jsonb(event["entities"]),
                Jsonb(event["assets"]),
                Jsonb(event["ocsf"]),
                Jsonb(event["details"]),
            ),
        )
    return event["id"]
