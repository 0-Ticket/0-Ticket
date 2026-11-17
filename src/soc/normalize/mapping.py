"""ELK hit 원본을 OCSF 객체와 알럿·이벤트 계약 dict로 바꾼다. DB를 읽지 않는다.

원본의 알럿 필드(kibana.alert.*)는 평평한 점 키이고 ECS 이벤트 필드는 중첩 객체일 수 있어,
_value가 평평한 키를 먼저, 없으면 중첩 경로를 읽는다.
"""

import ipaddress
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from soc.contracts import to_epoch_ms
from soc.ids import new_id
from soc.normalize.errors import NormalizeError
from soc.normalize.mask import mask_headers
from soc.tools.local_intel import normalize_technique_id

OCSF_VERSION = "1.9.0"

_WEB_INDEX = re.compile(r"^(?:\.ds-)?logs-(?:nginx|apache)\.access-")
_CLOUD_INDEX = re.compile(r"^(?:\.ds-)?logs-(?:aws\.cloudtrail|azure\.activitylogs|gcp\.audit)-")

SEVERITY_IDS = {"low": 2, "medium": 3, "high": 4, "critical": 5}
HTTP_ACTIVITY_IDS = {
    "CONNECT": 1,
    "DELETE": 2,
    "GET": 3,
    "HEAD": 4,
    "OPTIONS": 5,
    "POST": 6,
    "PUT": 7,
    "TRACE": 8,
    "PATCH": 9,
}
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
UNKNOWN_ID = 0
OTHER_ID = 99
MAX_DIGITS = 9
ALERT_SOURCES = ("suricata", "modsecurity")
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
_HOST_PORT = re.compile(r"\[([^\]]+)\](?::\d{1,5})?|([^:\[\]]+):\d{1,5}")


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
        outcome: 결과 품질. Alert만 "ok"·"partial"·"fallback"이고 Event는 None이다.
        error_code: partial·fallback의 사유 코드(errors.PARTIAL_REASONS, FALLBACK_REASONS).
        missing_fields: 얻지 못한 OCSF 경로 목록.
        source: 알럿 소스 이름. suricata·modsecurity·guardduty·unknown. Event는 None이다.
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
    """원본 종류와 인덱스 이름으로 알맞은 변환을 고른다.

    Args:
        raw: 정규화할 원본 한 행.

    Raises:
        NormalizeError: 필수 값이 없거나 시각을 읽을 수 없다(validation_failed).
    """
    if raw.kind == "alert":
        return _alert(raw)
    index = raw.original.get("_index")
    index = index if isinstance(index, str) else ""
    if _WEB_INDEX.match(index):
        return _web_event(raw)
    if _CLOUD_INDEX.match(index):
        return _cloud_event(raw)
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
    row = {
        "id": new_id("alt"),
        "raw_id": raw.id,
        "time": time_ms,
        "severity": UNKNOWN_ID,
        "title": message,
        "rule_id": None,
        "entities": [],
        "assets": [],
        "triage": None,
        "ocsf": _ocsf(0, 0, UNKNOWN_ID, time_ms, UNKNOWN_ID, {"message": message}),
        "details": {"fallback": details},
    }
    return Result("alert", row, "fallback", reason, (), "unknown")


def _finding(raw: RawRow) -> Result:
    """Kibana 알럿 원본을 2004 Result로 바꾼다.

    Raises:
        _Fallback: _source·uid·룰 이름·생성 시각을 읽을 수 없다.
    """
    source = raw.original.get("_source")
    if not isinstance(source, dict):
        raise _Fallback("invalid_source")
    uid = _text(source, "kibana.alert.uuid") or _text(raw.original, "_id")
    if uid is None:
        raise _Fallback("missing_uid")
    title = _text(source, "kibana.alert.rule.name")
    if title is None:
        raise _Fallback("missing_title")
    try:
        time_ms = _time_ms(source, "kibana.alert.start", "@timestamp")
    except NormalizeError:
        raise _Fallback("bad_time") from None
    original_ms = _optional_time_ms(source, "kibana.alert.original_time")
    start_ms = time_ms if original_ms is None else original_ms
    severity_name = _text(source, "kibana.alert.severity")
    severity = SEVERITY_IDS.get(severity_name, UNKNOWN_ID)
    rule_id = _text(source, "kibana.alert.rule.rule_id")
    alert_source = _detect_source(source)
    incomplete = [
        path
        for path, found in (
            ("finding_info.analytic.uid", rule_id is not None),
            ("severity_id", severity_name in SEVERITY_IDS),
            ("start_time", original_ms is not None),
        )
        if not found
    ]
    entities, bad_ips = _alert_entities(source)
    description = _text(source, "kibana.alert.rule.description")
    destination = _text(source, "destination.ip")
    extra = {
        "finding_info": {
            "uid": uid,
            "title": title,
            "desc": description,
            "created_time": time_ms,
            "analytic": {"name": title, "uid": rule_id, "type_id": ANALYTIC_RULE},
            "attacks": _attacks(source) or None,
        },
        "is_alert": True,
        "status_id": 1,
        "start_time": start_ms,
        "end_time": start_ms,
        "message": description or title,
        "risk_score": _rounded(_value(source, "kibana.alert.risk_score")),
        "observables": _observables(entities) or None,
        "evidences": [{"dst_endpoint": {"ip": destination}}]
        if destination is not None and _is_ip(destination)
        else None,
    }
    ocsf = _ocsf(2004, 2, 1, time_ms, severity, extra)
    row = {
        "id": new_id("alt"),
        "raw_id": raw.id,
        "time": start_ms,
        "severity": severity,
        "title": title,
        "rule_id": rule_id,
        "entities": entities,
        "assets": [],
        "triage": None,
        "ocsf": ocsf,
        "details": {},
    }
    # 소스별 매퍼가 값을 더해도 마지막에 한 번 가려 빠뜨리지 못하게 한다
    row["ocsf"], row["details"] = mask_headers(row["ocsf"]), mask_headers(row["details"])
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


def _detect_source(source: dict[str, Any]) -> str:
    """알럿 소스를 고른다. event.module, 없으면 kibana.alert.original_event.module, 그것도 없으면
    최상위 guardduty 키로 판별한다.

    Args:
        source: raw.original["_source"].
    """
    module = _text(source, "event.module") or _text(source, "kibana.alert.original_event.module")
    if module in ALERT_SOURCES:
        return module
    return "guardduty" if isinstance(source.get("guardduty"), dict) else "unknown"


def _alert_entities(source: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """ECS 표준 필드에서 Alert 엔티티를 만든다. 센서 필드(host.name, agent.*)는 읽지 않는다.

    Args:
        source: raw.original["_source"].

    Returns:
        (엔티티 목록, 틀린 IP라서 얻지 못한 OCSF 경로 목록).
    """
    entities: list[dict[str, Any]] = []
    missing: list[str] = []

    def add(entity_type: str, value: str, role: str) -> None:
        entity = {"type": entity_type, "value": value, "role": role}
        if entity not in entities:
            entities.append(entity)

    for path, role, gap in (
        ("source.ip", "src", "evidences[].src_endpoint.ip"),
        ("destination.ip", "dst", "evidences[].dst_endpoint.ip"),
    ):
        value = _text(source, path)
        if value is None:
            continue
        if _is_ip(value):
            add("ip", value, role)
        else:
            missing.append(gap)
    user = _text(source, "user.name")
    if user is not None:
        add("user", user, "actor")
    for path in ("url.domain", "destination.domain"):
        value = _text(source, path)
        if value is not None:
            host = _strip_port(value)
            add("ip" if _is_ip(host) else "domain", host, "dst")
    url = _text(source, "url.original")
    if url is not None:
        add("url", url, "dst")
    return entities, missing


def _strip_port(value: str) -> str:
    """host:port, [v6]:port, [v6]에서 포트와 대괄호를 뗀다. 맨 IPv6(콜론 여러 개)는 그대로 둔다.

    Args:
        value: domain 후보 값.
    """
    match = _HOST_PORT.fullmatch(value)
    return (match.group(1) or match.group(2)) if match else value


def _is_ip(value: str) -> bool:
    """IPv4·IPv6 형식이면 True.

    Args:
        value: 검사할 문자열.
    """
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


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


def _rounded(value: Any) -> int | None:
    """유한한 숫자를 반올림한 정수로 바꾼다. 그 밖은 None.

    Args:
        value: kibana.alert.risk_score 값.
    """
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(value)


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


def _web_event(raw: RawRow) -> Result:
    """웹 접근 로그 이벤트를 HTTP Activity(4002)로 바꾼다.

    Args:
        raw: nginx 또는 apache 접근 로그 인덱스의 이벤트 원본.
    """
    source = _source(raw)
    method = _text(source, "http.request.method")
    method = method.upper() if method else None
    path = _text(source, "url.path")
    url_string = _text(source, "url.original")
    code = _integer(source, "http.response.status_code")
    extra = {
        "src_endpoint": {"ip": _text(source, "source.ip")},
        "dst_endpoint": {"ip": _text(source, "destination.ip")},
        "http_request": {
            "http_method": method if method in HTTP_ACTIVITY_IDS else None,
            "url": {
                "path": path,
                "url_string": url_string,
                "hostname": _text(source, "url.domain"),
            },
            "user_agent": _text(source, "user_agent.original"),
        },
        "http_response": {"code": code},
    }
    activity_id = HTTP_ACTIVITY_IDS.get(method, OTHER_ID) if method else UNKNOWN_ID
    summary = _summary(source, method, path or url_string, code)
    return _event(raw, source, 4002, 4, activity_id, extra, summary)


def _cloud_event(raw: RawRow) -> Result:
    """클라우드 감사 로그 이벤트를 API Activity(6003)로 바꾼다.

    Args:
        raw: CloudTrail, Azure 활동 로그, GCP 감사 로그 인덱스의 이벤트 원본.
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
    summary = _summary(source, operation, _text(source, "user.name"))
    return _event(raw, source, 6003, 6, activity_id, extra, summary)


def _base_event(raw: RawRow) -> Result:
    """지원 클래스가 없는 이벤트를 Base Event(0)로 바꾼다.

    Args:
        raw: 웹·클라우드 인덱스가 아닌 이벤트 원본.
    """
    source = _source(raw)
    return _event(
        raw,
        source,
        0,
        0,
        UNKNOWN_ID,
        {"unmapped": {"destination": {"ip": _text(source, "destination.ip")}}},
        _summary(source, _text(source, "event.action")),
    )


def _event(
    raw: RawRow,
    source: dict[str, Any],
    class_uid: int,
    category_uid: int,
    activity_id: int,
    extra: dict[str, Any],
    summary: str,
) -> Result:
    """OCSF 객체를 만들고 events 행으로 감싼다.

    Args:
        raw: 원본 한 행.
        source: raw.original["_source"].
        class_uid: OCSF 클래스 번호.
        category_uid: 클래스가 속한 OCSF 카테고리 번호.
        activity_id: OCSF activity_id.
        extra: 클래스별 OCSF 속성. 비어 있는 값은 버린다.
        summary: events.summary에 넣을 한 줄 설명.
    """
    time_ms = _time_ms(source, "@timestamp")
    ocsf = _ocsf(class_uid, category_uid, activity_id, time_ms, 1, extra)
    row = {
        "id": new_id("evt"),
        "raw_id": raw.id,
        "time": time_ms,
        "ocsf_class": class_uid,
        "summary": summary,
        "entities": _entities(source),
        "assets": [],
        "ocsf": ocsf,
        "details": {},
    }
    return Result("event", row)


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
    return {
        "class_uid": class_uid,
        "category_uid": category_uid,
        "activity_id": activity_id,
        "type_uid": class_uid * 100 + activity_id,
        "severity_id": severity_id,
        "time": time_ms,
        "metadata": {
            "version": OCSF_VERSION,
            "product": {"name": "Elasticsearch", "vendor_name": "Elastic"},
        },
        **_compact(extra),
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


def _summary(source: dict[str, Any], *parts: object) -> str:
    """값이 있는 부분을 공백으로 이어 한 줄로 만든다. 모두 비면 event.dataset을 쓴다.

    Args:
        source: raw.original["_source"].
        parts: 요약에 넣을 값들. None이나 빈 문자열은 건너뛴다.
    """
    text = " ".join(str(part) for part in parts if part)
    return text or _text(source, "event.dataset") or "event"


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


def _value(source: dict[str, Any], path: str) -> Any:
    """평평한 점 키를 먼저, 없으면 중첩 경로를 따라 값을 읽는다. 없으면 None.

    Args:
        source: raw.original["_source"].
        path: 점으로 이은 필드 이름. 예: "http.response.status_code".
    """
    if path in source:
        return source[path]
    node: Any = source
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _text(source: dict[str, Any], path: str) -> str | None:
    """비어 있지 않은 문자열 값만 돌려준다. 그 밖은 None.

    Args:
        source: raw.original["_source"].
        path: 점으로 이은 필드 이름.
    """
    value = _value(source, path)
    return value if isinstance(value, str) and value.strip() else None


def _integer(source: dict[str, Any], path: str) -> int | None:
    """정수 값 또는 ASCII 숫자만 든 짧은 문자열을 정수로 돌려준다. 그 밖은 None.

    Args:
        source: raw.original["_source"].
        path: 점으로 이은 필드 이름.
    """
    value = _value(source, path)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= MAX_DIGITS:
        return int(value)
    return None


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
