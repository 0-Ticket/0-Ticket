"""ELK hit 원본을 OCSF 객체와 알럿·이벤트 계약 dict로 바꾼다. DB를 읽지 않는다.

원본의 알럿 필드(kibana.alert.*)는 평평한 점 키이고 ECS 이벤트 필드는 중첩 객체일 수 있어,
_value가 평평한 키를 먼저, 없으면 중첩 경로를 읽는다.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from soc.contracts import to_epoch_ms
from soc.contracts.alert import alert_rule_id, alert_severity, alert_time, alert_title
from soc.contracts.event import EMPTY_SUMMARY, event_class, event_summary, event_time
from soc.ids import new_id
from soc.normalize.errors import NormalizeError
from soc.normalize.event_tables import load_event_tables, summary_text
from soc.normalize.mask import mask_headers
from soc.normalize.paths import read_value as _value
from soc.normalize.tables import (
    COMMON,
    Table,
    apply_entities,
    apply_table,
    load_tables,
    matching_source,
)
from soc.normalize.transforms import HTTP_ACTIVITY_IDS
from soc.tools.local_intel import normalize_technique_id

OCSF_VERSION = "1.9.0"
# 소스 표가 요청 시각을 얻지 못해 클래스 표의 @timestamp를 쓴 경우의 누락 경로와 사유(#351)
REQUEST_TIME_GAP = "metadata.original_time"
REQUEST_TIME_CODE = "missing_request_time_used_at_timestamp"

_WEB_INDEX = re.compile(r"^(?:\.ds-)?logs-(?:nginx|apache)\.access-")
_CLOUD_INDEX = re.compile(r"^(?:\.ds-)?logs-(?:aws\.cloudtrail|azure\.activitylogs|gcp\.audit)-")

API_ACTIVITY_PREFIXES = (
    ("Create", 1),
    ("Run", 1),
    ("Start", 1),
    ("Launch", 1),
    ("Add", 1),
    ("Get", 2),
    ("List", 2),
    ("Describe", 2),
    ("Head", 2),
    ("Update", 3),
    ("Modify", 3),
    ("Delete", 4),
    ("Remove", 4),
)
ENTITY_FIELDS = (
    ("source.ip", "ip", "src"),
    ("destination.ip", "ip", "dst"),
    ("host.name", "host", None),
    ("user.name", "user", "actor"),
    ("url.domain", "domain", None),
    ("url.original", "url", None),
)
_ABSENT = object()
UNKNOWN_ID = 0
OTHER_ID = 99
# OCSF observable type_id(1.9.0): Hostname 1, IP Address 2, User Name 4, URL String 6, Hash 8,
# Process Name 9
OBSERVABLE_TYPE_IDS = {
    "ip": 2,
    "host": 1,
    "domain": 1,
    "user": 4,
    "url": 6,
    "file_hash": 8,
    "process": 9,
}
ANALYTIC_RULE = 1
# 이벤트 클래스(D-067)가 속한 OCSF 카테고리 번호
EVENT_CATEGORIES = {0: 0, 2003: 2, 3002: 3, 4001: 4, 4002: 4, 4003: 4, 6003: 6}
# common 표에서 값을 얻지 못하면 해석할 수 없는 알럿으로 보고 폴백하는 target과 사유(D-059).
# 순서대로 본다
_FALLBACK_TARGETS = (
    ("finding_info.uid", "missing_uid"),
    ("finding_info.title", "missing_title"),
    ("time", "bad_time"),
)


@dataclass(frozen=True)
class RawRow:
    """정규화할 raw_records 한 행.

    Attributes:
        id: raw_records.id.
        kind: 원본 종류. "alert" 또는 "event".
        original: ELK 검색 응답의 hit 객체 그대로(_index, _id, _source를 가진다).
        fetched_at: 원본을 가져온 시각(epoch 밀리초). 폴백 Alert의 시각 대체에만 쓴다.
    """

    id: str
    kind: str
    original: dict[str, Any]
    fetched_at: int | None = None


@dataclass(frozen=True)
class Result:
    """정규화 결과 한 건.

    Attributes:
        kind: 결과 종류. "alert"이면 alerts, "event"이면 events 테이블에 저장한다.
        row: 계약 모양의 dict. assets는 빈 목록이며 자산 조회 뒤에 채운다.
        outcome: 결과 품질. "ok"·"partial"·"fallback".
        error_code: partial·fallback의 사유 코드(errors의 PARTIAL_REASONS, FALLBACK_REASONS,
            EVENT_PARTIAL_REASONS, EVENT_FALLBACK_REASONS).
        missing_fields: 얻지 못한 OCSF 경로 목록.
        source: 소스 이름. Alert는 suricata·modsecurity·guardduty·unknown. Event는 일치한 소스 표
            이름, 인덱스 규칙이면 class_4002·class_6003, 지원 매핑이 없으면 unknown.
    """

    kind: str
    row: dict[str, Any]
    outcome: str | None = None
    error_code: str | None = None
    missing_fields: tuple[str, ...] = ()
    source: str | None = None


class _Fallback(Exception):
    """Kibana 알럿으로 읽을 수 없다. reason은 errors.FALLBACK_REASONS 중 하나."""

    def __init__(self, reason: str) -> None:
        """폴백 사유를 가진 예외를 만든다."""
        super().__init__(reason)
        self.reason = reason


def normalize(raw: RawRow) -> Result:
    """원본 종류와 이벤트 소스 표를 보고 변환을 고른다. 소스가 없으면 인덱스를 본다.

    Args:
        raw: 정규화할 원본 한 행.

    Raises:
        NormalizeError: 필수 값이 없거나 시각을 읽을 수 없다(validation_failed).
    """
    if raw.kind == "alert":
        return _alert(raw)
    tables = load_event_tables()
    name = matching_source(tables.sources, raw.original)
    if name is not None:
        class_uid = tables.source_classes[name]
    else:
        index = raw.original.get("_index")
        index = index if isinstance(index, str) else ""
        if _WEB_INDEX.match(index):
            class_uid = 4002
        elif _CLOUD_INDEX.match(index):
            class_uid = 6003
        else:
            class_uid = 0
    if class_uid == 4002:
        return _web_event(
            raw, tables.classes[class_uid], tables.sources.get(name) if name else None, name
        )
    if class_uid == 6003:
        return _cloud_event(raw, name)
    return _base_event(raw)


def _alert(raw: RawRow) -> Result:
    """kind=alert 원본을 Detection Finding(2004)과 alerts 행으로 바꾼다. 읽을 수 없으면 폴백이다.

    Args:
        raw: kind가 alert인 원본.
    """
    try:
        return _finding(raw)
    except _Fallback as fallback:
        return fallback_alert(raw, fallback.reason)


def fallback_alert(raw: RawRow, reason: str) -> Result:
    """해석할 수 없는 알럿을 class 0 Base Event 모양의 Alert로 남긴다. 값을 지어내지 않는다.

    Args:
        raw: kind가 alert인 원본.
        reason: errors.FALLBACK_REASONS 중 하나.

    Raises:
        NormalizeError: 원본 @timestamp도 fetched_at도 없다(validation_failed).
    """
    source = raw.original.get("_source")
    time_ms = None
    if isinstance(source, dict):
        try:
            time_ms = _time_ms(source, "@timestamp")
        except NormalizeError:
            pass
    details = {"reason": reason}
    if time_ms is None:
        if raw.fetched_at is None:
            raise NormalizeError("validation_failed")
        time_ms = raw.fetched_at
        details["time_from"] = "fetched_at"
    message = f"정규화 실패: {reason}"
    ocsf = _ocsf(0, 0, UNKNOWN_ID, time_ms, UNKNOWN_ID, {"message": message})
    row = alert_row(new_id("alt"), raw.id, ocsf, [], {"fallback": details})
    return Result("alert", row, "fallback", reason, (), "unknown")


def _finding(raw: RawRow) -> Result:
    """Kibana 알럿 원본을 2004 Result로 바꾼다.

    Raises:
        _Fallback: _source·uid·룰 이름·생성 시각을 읽을 수 없다.
    """
    source = raw.original.get("_source")
    if not isinstance(source, dict):
        raise _Fallback("invalid_source")
    tables = load_tables()
    common = apply_table(tables[COMMON], raw.original)
    for target, reason in _FALLBACK_TARGETS:
        if target not in common.values:
            raise _Fallback(reason)
    time_ms = common.values["time"]
    original_ms = _optional_time_ms(source, "kibana.alert.original_time")
    start_ms = time_ms if original_ms is None else original_ms
    alert_source = _detect_source(raw.original)
    values, missing = common.values, common.missing
    found = apply_entities(tables[COMMON], raw.original)
    if alert_source in tables:
        # 소스 표의 entries는 common의 같은 target을 덮어쓴다. 원본에 값이 없으면 common 값이 남는다
        sourced = apply_table(tables[alert_source], raw.original)
        values = {**common.values, **sourced.values}
        missing = [t for t in dict.fromkeys([*common.missing, *sourced.missing]) if t not in values]
        apply_entities(tables[alert_source], raw.original, found)
    incomplete = [*missing, *(["start_time"] if original_ms is None else [])]
    entities, bad_ips = found.entities, found.missing
    extra = _nested(values)
    finding_info = extra["finding_info"]
    finding_info["analytic"]["type_id"] = ANALYTIC_RULE
    finding_info["attacks"] = _attacks(source) or None
    ocsf = finding_ocsf(extra, time_ms, entities, start_ms)
    # 소스별 매퍼가 값을 더해도 마지막에 한 번 가려 빠뜨리지 못하게 한다(컬럼은 가린 ocsf에서 파생)
    row = alert_row(new_id("alt"), raw.id, mask_headers(ocsf), entities)
    unknown = alert_source == "unknown"
    outcome = "partial" if unknown or incomplete else "ok"
    return Result(
        "alert",
        row,
        outcome,
        "unknown_source" if unknown else None,
        (*incomplete, *bad_ips),
        alert_source,
    )


def _nested(values: dict[str, Any]) -> dict[str, Any]:
    """점으로 이은 target 경로의 값들을 중첩 객체로 만든다.

    Args:
        values: target 경로 → 값. 배열(`[]`) 경로는 다루지 않는다.
    """
    nested: dict[str, Any] = {}
    for path, value in values.items():
        *parents, leaf = path.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return nested


def _detect_source(hit: dict[str, Any]) -> str:
    """알럿 소스를 고른다. 소스 표의 detect가 맞는 첫 표, 없으면 unknown.

    Args:
        hit: raw.original.
    """
    return matching_source(load_tables(), hit) or "unknown"


def _attacks(source: dict[str, Any]) -> list[dict[str, Any]]:
    """룰 태그의 attack.T####와 threat.technique.id를 합쳐 중복 없이 OCSF attack 객체로 만든다.

    형식이 틀린 값은 버린다.

    Args:
        source: raw.original["_source"].
    """
    ids: list[str] = []
    for path in ("kibana.alert.rule.tags", "threat.technique.id"):
        value = _value(source, path)
        for item in [value] if isinstance(value, str) else value if isinstance(value, list) else []:
            try:
                technique = normalize_technique_id(item) if isinstance(item, str) else None
            except ValueError:
                continue
            if technique is not None and technique not in ids:
                ids.append(technique)
    return [
        {
            "technique": {"uid": uid.partition(".")[0]},
            **({"sub_technique": {"uid": uid}} if "." in uid else {}),
        }
        for uid in ids
    ]


# 엔티티 (type, role) → evidences 요소. 대응이 없는 것(target·null role 등)은 뺀다(D-065)
_EVIDENCE_BUILDERS = {
    ("ip", "src"): lambda value: {"src_endpoint": {"ip": value}},
    ("ip", "dst"): lambda value: {"dst_endpoint": {"ip": value}},
    ("user", "actor"): lambda value: {"actor": {"user": {"name": value}}},
    ("domain", "dst"): lambda value: {"dst_endpoint": {"domain": value}},
    ("url", "dst"): lambda value: {"url": {"url_string": value}},
}


def _observables(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """엔티티 목록에서 OCSF observable을 만든다. 같은 type·값은 한 번만 넣는다.

    Args:
        entities: Alert 엔티티 목록.
    """
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for entity in entities:
        type_id = OBSERVABLE_TYPE_IDS[entity["type"]]
        seen.setdefault((type_id, entity["value"]), {"type_id": type_id, "value": entity["value"]})
    return list(seen.values())


def _evidences(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """엔티티에서 OCSF evidence 요소를 만든다. 엔티티 하나에 요소 하나, 같은 요소는 한 번만 둔다.

    Args:
        entities: Alert 엔티티 목록.
    """
    found: list[dict[str, Any]] = []
    for entity in entities:
        build = _EVIDENCE_BUILDERS.get((entity["type"], entity["role"]))
        if build is not None and (item := build(entity["value"])) not in found:
            found.append(item)
    return found


def finding_ocsf(
    extra: dict[str, Any], time_ms: int, entities: list[dict[str, Any]], start_ms: int | None = None
) -> dict[str, Any]:
    """Detection Finding(2004) OCSF 문서를 만든다. observables·evidences는 entities에서만 온다.

    Args:
        extra: 클래스별 OCSF 속성(finding_info 등). severity_id가 있으면 쓴다.
        time_ms: 생성 시각 `time`(epoch 밀리초).
        entities: Alert 엔티티 목록. 원본 컬럼이다.
        start_ms: `start_time`·`end_time`. 없으면 time_ms.
    """
    start = time_ms if start_ms is None else start_ms
    severity = extra.get("severity_id", UNKNOWN_ID)
    return _ocsf(
        2004,
        2,
        1,
        time_ms,
        severity,
        {
            **extra,
            "is_alert": True,
            "status_id": 1,
            "start_time": start,
            "end_time": start,
            "observables": _observables(entities) or None,
            "evidences": _evidences(entities) or None,
        },
    )


def derive_columns(ocsf: dict[str, Any]) -> dict[str, Any]:
    """ocsf 문서에서 alerts의 time·severity·title·rule_id를 만든다(D-065). 파생은 이 함수 하나다.

    읽는 규칙은 `soc.contracts.alert`의 헬퍼와 같다. time은 start_time, 없으면 time.
    title은 finding_info.title, 없으면 message. severity는 severity_id이고 컬럼 범위(0~6)
    밖(99 Other 등)은 0이다.

    Args:
        ocsf: 알럿의 OCSF 문서(2004 또는 폴백 0).
    """
    return {
        "time": alert_time(ocsf),
        "severity": alert_severity(ocsf),
        "title": alert_title(ocsf),
        "rule_id": alert_rule_id(ocsf),
    }


def with_derived_columns(row: dict[str, Any]) -> dict[str, Any]:
    """ocsf만 가진 alerts 행(시드 샘플)에 파생 컬럼 time·severity·title·rule_id를 채운다.

    Args:
        row: ocsf를 가진 alerts 행.
    """
    return {**row, **derive_columns(row["ocsf"])}


def alert_row(
    alert_id: str,
    raw_id: str,
    ocsf: dict[str, Any],
    entities: list[dict[str, Any]],
    details: dict[str, Any] | None = None,
    assets: list[Any] | None = None,
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """alerts 행 하나를 만든다. 컬럼 값은 ocsf에서 파생하고 그 밖의 칸은 받은 값이다.

    Args:
        alert_id: alerts.id.
        raw_id: raw_records.id.
        ocsf: 알럿의 OCSF 문서. 원본이다.
        entities: Alert 엔티티 목록. 원본이다.
        details: OCSF 속성이 아닌 값. 없으면 빈 객체.
        assets: 자산 목록. 정규화 뒤 자산 조회가 채우므로 기본은 빈 목록이다.
        triage: L1 1차 판정 상태.
    """
    return {
        "id": alert_id,
        "raw_id": raw_id,
        **derive_columns(ocsf),
        "entities": entities,
        "assets": assets or [],
        "triage": triage,
        "ocsf": ocsf,
        "details": details or {},
    }


def seed_event_ocsf(record: dict[str, Any], time_ms: int, message: str) -> dict[str, Any]:
    """시드 샘플의 ocsf(class_uid·activity_id와 클래스별 속성)로 이벤트 OCSF 문서를 만든다.

    category_uid·type_uid·severity_id·metadata·time·message는 정규화와 같은 방식으로 채운다.

    Args:
        record: 샘플의 ocsf. class_uid를 가지고 activity_id는 없으면 0이다.
        time_ms: 활동 발생 시각(epoch 밀리초).
        message: 한 줄 요약(events.summary의 원본).
    """
    class_uid = record["class_uid"]
    extra = {key: value for key, value in record.items() if key not in ("class_uid", "activity_id")}
    document = _ocsf(
        class_uid,
        EVENT_CATEGORIES[class_uid],
        record.get("activity_id", UNKNOWN_ID),
        time_ms,
        1,
        extra,
    )
    return {**document, "message": message}


def derive_event_columns(ocsf: dict[str, Any]) -> dict[str, Any]:
    """ocsf 문서에서 events의 time·ocsf_class·summary를 만든다(D-068). 파생은 이 함수 하나다.

    읽는 규칙은 `soc.contracts.event`의 헬퍼와 같다. time은 start_time, 없으면 time이고
    summary는 message다.

    Args:
        ocsf: 이벤트의 OCSF 문서.
    """
    return {
        "time": event_time(ocsf),
        "ocsf_class": event_class(ocsf),
        "summary": event_summary(ocsf),
    }


def with_derived_event_columns(row: dict[str, Any]) -> dict[str, Any]:
    """ocsf만 가진 events 행(시드 샘플)에 파생 컬럼 time·ocsf_class·summary를 채운다.

    Args:
        row: ocsf를 가진 events 행.
    """
    return {**row, **derive_event_columns(row["ocsf"])}


def event_row(
    event_id: str,
    raw_id: str,
    ocsf: dict[str, Any],
    entities: list[dict[str, Any]],
    details: dict[str, Any] | None = None,
    assets: list[Any] | None = None,
) -> dict[str, Any]:
    """events 행 하나를 만든다. 컬럼 값은 ocsf에서 파생하고 그 밖의 칸은 받은 값이다.

    Args:
        event_id: events.id.
        raw_id: raw_records.id.
        ocsf: 이벤트의 OCSF 문서. 원본이다.
        entities: Event 엔티티 목록.
        details: OCSF 속성이 아닌 값. 없으면 빈 객체.
        assets: 자산 목록. 정규화 뒤 자산 조회가 채우므로 기본은 빈 목록이다.
    """
    return {
        "id": event_id,
        "raw_id": raw_id,
        **derive_event_columns(ocsf),
        "entities": entities,
        "assets": assets or [],
        "ocsf": ocsf,
        "details": details or {},
    }


def _optional_time_ms(source: dict[str, Any], path: str) -> int | None:
    """시각 필드를 epoch 밀리초로 바꾼다. 없거나 읽을 수 없으면 None.

    Args:
        source: raw.original["_source"].
        path: 시각 필드 이름.
    """
    try:
        return _time_ms(source, path)
    except NormalizeError:
        return None


def _web_event(raw: RawRow, common: Table, specific: Table | None, name: str | None) -> Result:
    """HTTP 클래스 표에 소스 표의 값을 더해 4002 이벤트를 만든다.

    소스 표가 시각 항목을 가졌는데 그 필드가 아예 없어 클래스 표의 시각을 쓰면 partial이다.
    """
    source = _source(raw)
    applied = apply_table(common, raw.original)
    values, missing = applied.values, applied.missing
    found = apply_entities(common, raw.original)
    time_fallback = False
    if specific is not None:
        overlay = apply_table(specific, raw.original)
        missing = [*missing, *overlay.missing]
        for target in overlay.errors:
            values.pop(target, None)
        # 명시적인 null·잘못된 값도 원래 시각을 읽지 못한 경우다.
        # 소스의 시각 필드가 아예 없을 때만 클래스 표 시각을 사용한다.
        if "time" not in overlay.values:
            for entry in specific.entries:
                if entry.target == "time" and any(
                    _value(source, path, _ABSENT) is not _ABSENT for path in entry.sources
                ):
                    raise NormalizeError("validation_failed")
            time_fallback = any(entry.target == "time" for entry in specific.entries)
        if "activity_name" in overlay.values:
            values.pop("http_request.http_method", None)
        values.update(overlay.values)
        apply_entities(specific, raw.original, found)

    time_ms = values.pop("time", None)
    if time_ms is None:
        raise NormalizeError("validation_failed")
    method = values.get("http_request.http_method")
    if method is not None:
        activity_id = HTTP_ACTIVITY_IDS[method]
        values.pop("activity_name", None)
    else:
        activity_id = OTHER_ID if "activity_name" in values else UNKNOWN_ID
    # 다른 표가 값을 채운 항목은 누락이 아니다. 시각은 위에서 얻었다
    gaps = [t for t in dict.fromkeys(missing) if t not in values and t != "time"]
    if time_fallback:
        gaps.append(REQUEST_TIME_GAP)
    return _event(
        raw,
        source,
        4002,
        4,
        activity_id,
        _nested(values),
        time_ms=time_ms,
        entities=found.entities,
        source_name=name or "class_4002",
        missing=gaps,
        error_code=REQUEST_TIME_CODE if time_fallback else None,
    )


def _cloud_event(raw: RawRow, name: str | None) -> Result:
    """클라우드 감사 로그 이벤트를 API Activity(6003)로 바꾼다.

    Args:
        raw: CloudTrail, Azure 활동 로그, GCP 감사 로그 인덱스의 이벤트 원본.
        name: 일치한 소스 표 이름. 인덱스 규칙으로 골랐으면 None.
    """
    source = _source(raw)
    operation = _text(source, "event.action")
    extra = {
        "api": {
            "operation": operation,
            "service": {"name": _text(source, "event.provider")},
        },
        "actor": {
            "user": {
                "name": _text(source, "user.name"),
                "uid": _text(source, "user.entity.id"),
            }
        },
        "src_endpoint": {"ip": _text(source, "source.ip")},
        "dst_endpoint": {"ip": _text(source, "destination.ip")},
    }
    activity_id = UNKNOWN_ID
    if operation:
        activity_id = next(
            (id_ for prefix, id_ in API_ACTIVITY_PREFIXES if operation.startswith(prefix)),
            OTHER_ID,
        )
    if activity_id == OTHER_ID:
        extra["activity_name"] = operation
    return _event(raw, source, 6003, 6, activity_id, extra, source_name=name or "class_6003")


def _base_event(raw: RawRow) -> Result:
    """지원 클래스가 없는 이벤트를 Base Event(0)로 바꾼다.

    Args:
        raw: 웹·클라우드 인덱스가 아닌 이벤트 원본.
    """
    source = _source(raw)
    extra: dict[str, Any] = {"unmapped": {"destination": {"ip": _text(source, "destination.ip")}}}
    action = _text(source, "event.action")
    activity_id = OTHER_ID if action else UNKNOWN_ID
    if action:  # 출처의 활동 이름은 OCSF가 정한 자리(activity_id 99와 activity_name)에 둔다
        extra["activity_name"] = action
    return _event(
        raw,
        source,
        0,
        0,
        activity_id,
        extra,
        source_name="unknown",
        error_code="unsupported_event_mapping",
        fallback=True,
    )


def _event(
    raw: RawRow,
    source: dict[str, Any],
    class_uid: int,
    category_uid: int,
    activity_id: int,
    extra: dict[str, Any],
    *,
    time_ms: int | None = None,
    entities: list[dict[str, Any]] | None = None,
    source_name: str,
    missing: list[str] | None = None,
    error_code: str | None = None,
    fallback: bool = False,
) -> Result:
    """OCSF 객체를 만들고 events 행으로 감싼다. 요약은 message에 넣는다(D-068).

    Args:
        raw: 원본 한 행.
        source: raw.original["_source"].
        class_uid: OCSF 클래스 번호.
        category_uid: 클래스가 속한 OCSF 카테고리 번호.
        activity_id: OCSF activity_id.
        extra: 클래스별 OCSF 속성. 비어 있는 값은 버린다.
        source_name: 결과 품질의 소스 이름(소스 표 이름, class_N, unknown).
        missing: 품질 판정에 필요한데 얻지 못한 OCSF 경로.
        error_code: partial·fallback의 사유 코드.
        fallback: 지원 매핑이 없어 Base Event로 만들었는지.
    """
    if time_ms is None:
        time_ms = _time_ms(source, "@timestamp")
    if entities is None:
        entities = _entities(source)
    ocsf = _ocsf(class_uid, category_uid, activity_id, time_ms, 1, extra)
    # 요약: 1순위 클래스별 정의(mapping_tables/events), 2순위 event.dataset, 3순위 "event"
    ocsf["message"] = (
        summary_text(class_uid, ocsf) or _text(source, "event.dataset") or EMPTY_SUMMARY
    )
    row = event_row(new_id("evt"), raw.id, ocsf, entities)
    outcome = "fallback" if fallback else "partial" if missing else "ok"
    return Result("event", row, outcome, error_code, tuple(missing or ()), source_name)


def _ocsf(
    class_uid: int,
    category_uid: int,
    activity_id: int,
    time_ms: int,
    severity_id: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """모든 클래스가 공유하는 OCSF 속성에 클래스별 속성을 합친다.

    Args:
        class_uid: OCSF 클래스 번호.
        category_uid: 클래스가 속한 OCSF 카테고리 번호.
        activity_id: OCSF activity_id.
        time_ms: 이벤트 시각(epoch 밀리초).
        severity_id: OCSF severity_id.
        extra: 클래스별 OCSF 속성. 비어 있는 값은 버린다.
    """
    fields = _compact(extra)
    return {
        "class_uid": class_uid,
        "category_uid": category_uid,
        "activity_id": activity_id,
        "type_uid": class_uid * 100 + activity_id,
        "severity_id": severity_id,
        "time": time_ms,
        **fields,
        "metadata": {
            **fields.get("metadata", {}),
            "version": OCSF_VERSION,
            "product": {"name": "Elasticsearch", "vendor_name": "Elastic"},
        },
    }


def _entities(source: dict[str, Any]) -> list[dict[str, Any]]:
    """원본에서 읽을 수 있는 Entity 목록을 만든다.

    Args:
        source: raw.original["_source"].
    """
    entities = []
    for path, entity_type, role in ENTITY_FIELDS:
        value = _text(source, path)
        if value is not None:
            entities.append({"type": entity_type, "value": value, "role": role})
    return entities


def _source(raw: RawRow) -> dict[str, Any]:
    """원본의 _source 객체를 돌려준다.

    Args:
        raw: 원본 한 행.

    Raises:
        NormalizeError: _source가 객체가 아니다.
    """
    source = raw.original.get("_source")
    if not isinstance(source, dict):
        raise NormalizeError("validation_failed")
    return source


def _text(source: dict[str, Any], path: str) -> str | None:
    """비어 있지 않은 문자열 값만 돌려준다. 그 밖은 None.

    Args:
        source: raw.original["_source"].
        path: 점으로 이은 필드 이름.
    """
    value = _value(source, path)
    return value if isinstance(value, str) and value.strip() else None


def _time_ms(source: dict[str, Any], *paths: str) -> int:
    """처음으로 값이 있는 시각 필드를 epoch 밀리초로 바꾼다.

    Args:
        source: raw.original["_source"].
        paths: 시각 필드 이름을 우선순위 순으로. ISO 8601 문자열이며 시간대가 있어야 한다.

    Raises:
        NormalizeError: 값이 없거나 읽을 수 없다.
    """
    for path in paths:
        text = _text(source, path)
        if text is not None:
            try:
                return to_epoch_ms(datetime.fromisoformat(text))
            except ValueError:
                raise NormalizeError("validation_failed") from None
    raise NormalizeError("validation_failed")


def _compact(value: Any) -> Any:
    """객체 안의 None과 빈 객체를 재귀로 버린다.

    Args:
        value: 정리할 값. 객체가 아니면 그대로 돌려준다.
    """
    if not isinstance(value, dict):
        return value
    cleaned = {key: _compact(item) for key, item in value.items()}
    return {key: item for key, item in cleaned.items() if item is not None and item != {}}
