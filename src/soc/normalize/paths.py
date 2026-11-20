"""원본 hit 안의 값을 점으로 이은 경로로 읽는다. 정규화 매핑과 매핑표가 같이 쓴다."""

from typing import Any


def read_value(source: dict[str, Any], path: str, default: Any = None) -> Any:
    """평평한 점 키를 먼저, 없으면 중첩 경로를 따라 값을 읽는다. 없으면 default.

    Args:
        source: raw.original["_source"]. 매핑표의 `$.` 경로는 hit 전체.
        path: 점으로 이은 필드 이름. 예: "http.response.status_code".
    """
    if path in source:
        return source[path]
    node: Any = source
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
