"""OCSF 1.9.0 클래스 정의로 정규화 결과를 검사한다(D-007).

정의 파일은 ocsf/에 있다. 출처와 만든 방법은 ocsf/SOURCE.md에 적혀 있다.
검사 항목: 필수 속성, 정의에 없는 속성, 값 타입, enum 값, 목록, 객체 안쪽, at_least_one 제약.
"""

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from soc.normalize.errors import NormalizeError

_OCSF_DIR = Path(__file__).parent / "ocsf"
_INTEGER_TYPES = {"integer_t", "long_t", "timestamp_t", "port_t"}


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
    alternatives = definition.get("constraints", {}).get("at_least_one", [])
    if alternatives and not any(name in value for name in alternatives):
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
