"""ELK hit 원본을 OCSF 객체와 알럿·이벤트 계약 dict로 바꾼다. DB를 읽지 않는다.

원본의 알럿 필드(kibana.alert.*)는 평평한 점 키이고 ECS 이벤트 필드는 중첩 객체일 수 있어,
_value가 평평한 키를 먼저, 없으면 중첩 경로를 읽는다.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from soc.contracts import to_epoch_ms
from soc.ids import new_id
from soc.normalize.errors import NormalizeError

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


@dataclass(frozen=True)
class RawRow:
    """정규화할 raw_records 한 행.

    Attributes:
        id: raw_records.id.
        kind: 원본 종류. "alert" 또는 "event".
        original: ELK 검색 응답의 hit 객체 그대로(_index, _id, _source를 가진다).
    """

    id: str
    kind: str
    original: dict[str, Any]


@dataclass(frozen=True)
class Result:
    """정규화 결과 한 건.

    Attributes:
        kind: 결과 종류. "alert"이면 alerts, "event"이면 events 테이블에 저장한다.
        row: 계약 모양의 dict. assets는 빈 목록이며 자산 조회 뒤에 채운다.
    """

    kind: str
    row: dict[str, Any]


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
    """kind=alert 원본을 Detection Finding(2004)과 alerts 행으로 바꾼다.

    Args:
        raw: kind가 alert인 원본.
    """
    source = _source(raw)
    time_ms = _time_ms(source, "kibana.alert.original_time", "@timestamp")
    uid = raw.original.get("_id")
    title = _text(source, "kibana.alert.rule.name")
    if not isinstance(uid, str) or title is None:
        raise NormalizeError("validation_failed")
    severity = SEVERITY_IDS.get(_text(source, "kibana.alert.severity"), UNKNOWN_ID)
    ocsf = _ocsf(2004, 2, 1, time_ms, severity, {"finding_info": {"uid": uid, "title": title}})
    destination = _text(source, "destination.ip")
    if destination is not None:
        ocsf["evidences"] = [{"dst_endpoint": {"ip": destination}}]
    row = {
        "id": new_id("alt"),
        "raw_id": raw.id,
        "time": time_ms,
        "severity": severity,
        "title": title,
        "rule_id": _text(source, "kibana.alert.rule.rule_id"),
        "entities": _entities(source),
        "assets": [],
        "triage": None,
        "ocsf": ocsf,
        "details": {},
    }
    return Result("alert", row)


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
        raw, source, 0, 0, UNKNOWN_ID, {}, _summary(source, _text(source, "event.action"))
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
