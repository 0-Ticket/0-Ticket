"""수집 hit를 격리하고 키·원문을 재귀 한도와 무관하게 직렬화한다."""

import base64
import hashlib
import json
import math
from typing import Any

from soc.contracts.validate import MAX_JSON_DEPTH


def canonical_json_bytes(value: Any) -> bytes:
    """정렬된 키·압축 구분자·ASCII 이스케이프를 쓰는 결정적 JSON 바이트를 만든다."""
    return _iterative_json(value, sort_keys=True, item_separator=",", key_separator=":").encode(
        "ascii"
    )


def serialize_original(value: Any) -> str:
    """`json.dumps(value, ensure_ascii=True)`와 같은 JSON 글자를 반복형 순회로 만든다."""
    return _iterative_json(value, sort_keys=False, item_separator=", ", key_separator=": ")


def exceeds_depth(value: Any, max_depth: int = MAX_JSON_DEPTH) -> bool:
    """dict/list가 겹친 수가 max_depth보다 큰지 재귀 없이 확인한다."""
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, dict):
            if depth > max_depth:
                return True
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list | tuple):
            if depth > max_depth:
                return True
            stack.extend((item, depth + 1) for item in current)
    return False


def contains_nonfinite(value: Any) -> bool:
    """값 안에 NaN 또는 양·음 Infinity가 있는지 반복형 순회로 찾는다."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, float) and not math.isfinite(current):
            return True
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list | tuple):
            stack.extend(current)
    return False


def valid_sort_value(hit: Any) -> bool:
    """hit.sort[0]이 bool이 아닌 0 이상의 정수이면 True다."""
    if not isinstance(hit, dict):
        return False
    sort = hit.get("sort")
    if not isinstance(sort, list) or not sort:
        return False
    value = sort[0]
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def has_bad_sort(hit: Any) -> bool:
    """hit에 sort[0]이 없거나 체크포인트로 쓸 수 없으면 True다."""
    return not valid_sort_value(hit)


def quarantine_key(source_kind: str, source_key: str, hit: Any) -> str:
    """격리 전용 v1 합성 키를 만든다. 입력 hit는 바꾸지 않는다."""
    if isinstance(hit, dict):
        index = hit.get("_index")
        document_id = hit.get("_id")
        sort = hit.get("sort")
        has_sort_value = isinstance(sort, list) and bool(sort)
        sort_value = sort[0] if has_sort_value else None
        projected_hit = dict(hit)
        projected_hit.pop("_score", None)
        if has_sort_value:
            projected_hit["sort"] = sort[:1]
    else:
        index = None
        document_id = None
        has_sort_value = False
        sort_value = None
        projected_hit = hit

    payload = {
        "source_kind": source_kind,
        "source_key": source_key,
        "hit": projected_hit,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    index_token = _string_token(index)
    id_token = _string_token(document_id)
    sort_token = _value_token(sort_value) if has_sort_value else "n"
    return f"synthetic:v1:{index_token}:{id_token}:{sort_token}:{digest}"


def _string_token(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "n"
    encoded = serialize_original(value).encode("ascii")
    return _base64_token(encoded)


def _value_token(value: Any) -> str:
    return _base64_token(canonical_json_bytes(value))


def _base64_token(encoded: bytes) -> str:
    payload = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    if len(payload) > 128:
        return "h" + hashlib.sha256(encoded).hexdigest()
    return "v" + payload


def _iterative_json(
    value: Any,
    *,
    sort_keys: bool,
    item_separator: str,
    key_separator: str,
) -> str:
    """JSONEncoder의 dict/list 처리를 반복형 스택으로 한다."""
    chunks: list[str] = []
    active: set[int] = set()
    stack: list[tuple[str, Any]] = [("value", value)]

    while stack:
        kind, current = stack.pop()
        if kind == "text":
            chunks.append(current)
            continue
        if kind == "leave":
            active.remove(current)
            continue
        if isinstance(current, dict):
            identity = id(current)
            if identity in active:
                raise ValueError("Circular reference detected")
            active.add(identity)
            items = list(current.items())
            if sort_keys:
                items.sort(key=lambda item: item[0])
            events: list[tuple[str, Any]] = [("text", "{")]
            for index, (key, item) in enumerate(items):
                if index:
                    events.append(("text", item_separator))
                events.append(("value", _key_as_string(key)))
                events.append(("text", key_separator))
                events.append(("value", item))
            events.extend([("text", "}"), ("leave", identity)])
            stack.extend(reversed(events))
            continue
        if isinstance(current, list | tuple):
            identity = id(current)
            if identity in active:
                raise ValueError("Circular reference detected")
            active.add(identity)
            events = [("text", "[")]
            for index, item in enumerate(current):
                if index:
                    events.append(("text", item_separator))
                events.append(("value", item))
            events.extend([("text", "]"), ("leave", identity)])
            stack.extend(reversed(events))
            continue

        if isinstance(current, str):
            chunks.append(json.dumps(current, ensure_ascii=True))
        elif current is None or isinstance(current, bool | int | float):
            chunks.append(json.dumps(current, ensure_ascii=True, allow_nan=True))
        else:
            raise TypeError(f"Object of type {type(current).__name__} is not JSON serializable")

    return "".join(chunks)


def _key_as_string(key: Any) -> str:
    """json.dumps가 허용하는 dict key를 문자열로 만든다."""
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int | float):
        return json.dumps(key, ensure_ascii=True, allow_nan=True)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")
