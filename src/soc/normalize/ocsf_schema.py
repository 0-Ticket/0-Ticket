"""OCSF 1.9.0 클래스 정의로 정규화 결과를 검사한다(D-007).

정의 파일은 ocsf/에 있다. 출처와 만든 방법은 ocsf/SOURCE.md에 적혀 있다.
검사 항목: 필수 속성, 정의에 없는 속성, 값 타입, enum 값, 목록, 객체 안쪽,
at_least_one·just_one 제약.
"""

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from soc.normalize.errors import NormalizeError

_OCSF_DIR = Path(__file__).parent / "ocsf"
_INTEGER_TYPES = {"integer_t", "long_t", "timestamp_t", "port_t"}
# 로더가 검사하는 constraints 종류. 다른 종류가 정의에 있으면 스키마 고정 스크립트가 실패한다
SUPPORTED_CONSTRAINTS = frozenset({"at_least_one", "just_one"})


def validate_ocsf(ocsf: dict[str, Any]) -> None:
    """OCSF 객체 하나가 자기 class_uid의 클래스 정의를 지키는지 검사한다.

    Args:
        ocsf: 알럿·이벤트 행의 ocsf 객체. class_uid는 0, 2004, 4002, 6003 중 하나여야 한다.

    Raises:
        NormalizeError: 정의를 어기면 schema_failed.
    """
    class_uid = ocsf.get("class_uid")
    definition = _class_definition(class_uid) if type(class_uid) is int else None
    if definition is None or not _object_is_valid(definition, ocsf):
        raise NormalizeError("schema_failed")


def validate_alert_ocsf(alert: dict[str, Any]) -> None:
    """Alert JSON(D-066)의 OCSF 부분을 검사한다. 우리 값인 details는 빼고 검사한다.

    Args:
        alert: 조립한 Alert JSON. details를 뺀 나머지가 OCSF 문서다.

    Raises:
        NormalizeError: 정의를 어기면 schema_failed.
    """
    validate_ocsf({key: value for key, value in alert.items() if key != "details"})


def _object_is_valid(definition: dict[str, Any], value: dict[str, Any]) -> bool:
    """객체 하나가 정의의 필수·제약·속성 규칙을 지키는지 본다.

    Args:
        definition: 클래스 또는 객체 정의(attributes와 선택적 constraints를 가진다).
        value: 검사할 객체.
    """
    attributes = definition["attributes"]
    required = [
        name for name, attribute in attributes.items() if attribute.get("requirement") == "required"
    ]
    if any(name not in value for name in required):
        return False
    constraints = definition.get("constraints", {})
    alternatives = constraints.get("at_least_one", [])
    if alternatives and not any(name in value for name in alternatives):
        return False
    exclusive = constraints.get("just_one", [])
    if exclusive and sum(name in value for name in exclusive) != 1:
        return False
    return all(
        name in attributes and _attribute_is_valid(attributes[name], item)
        for name, item in value.items()
    )


def _attribute_is_valid(attribute: dict[str, Any], item: Any) -> bool:
    """속성 값이 목록 여부와 값 규칙을 지키는지 본다.

    Args:
        attribute: 속성 정의(type, object_type, is_array, enum 중 있는 것).
        item: 검사할 값. 목록 속성이면 목록이어야 한다.
    """
    if attribute.get("is_array"):
        return isinstance(item, list) and all(_value_is_valid(attribute, each) for each in item)
    return _value_is_valid(attribute, item)


def _value_is_valid(attribute: dict[str, Any], item: Any) -> bool:
    """값 하나가 속성의 타입·enum·안쪽 객체 정의를 지키는지 본다.

    Args:
        attribute: 속성 정의(type, object_type, enum 중 있는 것).
        item: 검사할 값 하나. generic object는 JSON 객체, 나머지는 등록된 정의로 검사한다.
    """
    kind = attribute["type"]
    if kind == "object_t":
        if attribute.get("object_type") == "object":
            return isinstance(item, dict) and _json_value_is_valid(item)
        nested = _object_definitions().get(attribute.get("object_type", ""))
        return isinstance(item, dict) and nested is not None and _object_is_valid(nested, item)
    if kind in _INTEGER_TYPES:
        matches = isinstance(item, int) and not isinstance(item, bool)
    elif kind == "float_t":
        matches = isinstance(item, int | float) and not isinstance(item, bool)
        matches = matches and math.isfinite(item)
    elif kind == "json_t":
        matches = _json_value_is_valid(item)
    elif kind == "boolean_t":
        matches = isinstance(item, bool)
    else:
        matches = isinstance(item, str)
    return matches and ("enum" not in attribute or str(item) in attribute["enum"])


def _json_value_is_valid(value: Any) -> bool:
    """이름 없는 OCSF object의 값이 JSON으로 보존되는지 확인한다.

    Args:
        value: 문자열 키 객체, 목록, JSON 기본 값만 허용하는 중첩 값.
    """
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _json_value_is_valid(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_json_value_is_valid(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, bool, int))


def has_class_definition(class_uid: object) -> bool:
    """ocsf/classes/에 이 클래스 번호의 정의 파일이 있으면 True. 정수가 아니면 False.

    수집 설정의 `class`(D-067)가 받아 둔 클래스만 허용하는 데 쓴다. bool·문자열·실수는
    번호로 보지 않는다.

    Args:
        class_uid: 확인할 값.
    """
    return type(class_uid) is int and _class_definition(class_uid) is not None


def field_definition(class_uid: int, path: str) -> dict[str, Any] | None:
    """클래스 정의에서 경로의 속성 정의를 찾는다. 없으면 None.

    Args:
        class_uid: OCSF 클래스 번호. 0 또는 2004 등 ocsf/classes/에 있는 것.
        path: 점으로 이은 OCSF 경로. 배열 속성은 `[]`를 붙여도 된다.
            예: "finding_info.analytic.uid", "evidences[].dst_endpoint.ip".

    Returns:
        속성 정의(type, requirement, is_array, object_type, enum 중 있는 것).
    """
    definition = _class_definition(class_uid)
    parts = path.split(".")
    for index, part in enumerate(parts):
        if definition is None or not part.removesuffix("[]"):
            return None
        attribute = definition["attributes"].get(part.removesuffix("[]"))
        if attribute is None or index == len(parts) - 1:
            return attribute
        if attribute["type"] != "object_t":
            return None
        definition = _object_definitions().get(attribute.get("object_type", ""))
    return None


def required_children(class_uid: int, path: str = "") -> list[str]:
    """클래스(path가 빈 문자열) 또는 그 안 객체의 필수 속성 이름을 정의 순서대로 돌려준다.

    Args:
        class_uid: OCSF 클래스 번호.
        path: 객체 속성의 경로. 예: "finding_info.analytic". 객체가 아니거나 없으면 빈 목록.
    """
    if path:
        attribute = field_definition(class_uid, path)
        if attribute is None or attribute["type"] != "object_t":
            return []
        definition = _object_definitions().get(attribute.get("object_type", ""))
    else:
        definition = _class_definition(class_uid)
    attributes = definition["attributes"] if definition else {}
    return [name for name, item in attributes.items() if item.get("requirement") == "required"]


@cache
def _class_definition(class_uid: int) -> dict[str, Any] | None:
    """ocsf/classes/<class_uid>.json을 읽는다. 파일이 없으면 None.

    Args:
        class_uid: OCSF 클래스 번호.
    """
    path = _OCSF_DIR / "classes" / f"{class_uid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@cache
def _object_definitions() -> dict[str, Any]:
    """ocsf/objects.json의 객체 정의를 읽는다."""
    return json.loads((_OCSF_DIR / "objects.json").read_text(encoding="utf-8"))
