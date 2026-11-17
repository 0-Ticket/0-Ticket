"""정규화 결과(ocsf, details)의 민감 헤더 값을 가린다(#326).

dict 키가 Cookie·Set-Cookie·Authorization(대소문자 무시)이면 값을 통째로, 문자열은 줄 시작이
`Name:`인 줄의 값 부분을 가린다. raw_records.original_text는 바꾸지 않는다.
shortcut: 줄 중간의 `Cookie:`와 다른 헤더 이름은 가리지 않는다.
소스별 매퍼가 새 헤더를 복사하면 `_HEADER_KEYS`와 `_HEADER_LINE`에 더한다.
"""

import re
from typing import Any

MASKED = "[REDACTED]"
_HEADER_KEYS = {"cookie", "set-cookie", "authorization"}
_HEADER_LINE = re.compile(
    r"^([ \t]*(?:cookie|set-cookie|authorization))[ \t]*:[^\r\n]*", re.IGNORECASE | re.MULTILINE
)


def mask_headers(value: Any) -> Any:
    """값 안의 민감 헤더 값을 가린 새 값을 돌려준다. 입력은 바꾸지 않는다.

    Args:
        value: 정규화 결과의 일부. dict·list는 안쪽까지, 문자열은 줄 단위로 본다.
    """
    if isinstance(value, str):
        return _HEADER_LINE.sub(rf"\1: {MASKED}", value)
    if isinstance(value, dict):
        return {
            key: MASKED
            if isinstance(key, str) and key.lower() in _HEADER_KEYS
            else mask_headers(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_headers(item) for item in value]
    return value
