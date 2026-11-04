"""Agent Log에 쓰기 직전 비밀 값을 [REDACTED]로 가린다(안전장치).

입출력에 비밀 값을 넣지 않는 것이 먼저다. 이 함수는 그래도 섞여 든 값을 한 번 더 지운다.
가리는 것은 세 가지다.
1. 설정의 *_env가 가리키는 환경변수의 실제 값. 여러 줄인 값(SSH 개인 키, #213)은 값 전체와 함께
   줄마다 가린다. JSON 문자열 속에서는 줄바꿈이 이스케이프(\\n)로 바뀌어 값 전체가
   맞지 않기 때문이다.
2. DB 주소(DATABASE_URL, AGENT_DATABASE_URL)의 비밀번호, 그리고 문자열 속 URL의 비밀번호 자리
3. password=, Authorization: Bearer, api_key 모양의 값과, 이름이 password·api_key인 객체 키의 값
"""

import os
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from psycopg.conninfo import conninfo_to_dict

REDACTED = "[REDACTED]"

# 너무 짧은 값은 평범한 낱말까지 지우므로 가리지 않는다.
_MIN_SECRET_LENGTH = 4
_DATABASE_URL_ENVS = ("DATABASE_URL", "AGENT_DATABASE_URL")
_SECRET_KEYS = frozenset({"password", "passwd", "api_key", "apikey", "api-key", "authorization"})

_URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(?=@)", re.IGNORECASE)
_KEY_VALUE = re.compile(
    r"(\b(?:password|passwd|pwd|api[_-]?key)\b[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&}]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def build_redactor(
    config: Mapping[str, Any], environ: Mapping[str, str] | None = None
) -> Callable[[Any], Any]:
    """설정과 환경변수로 가릴 값을 모아, JSON 값을 받아 가린 사본을 돌려주는 함수를 만든다."""
    environ = os.environ if environ is None else environ
    secrets: set[str] = set()
    for key, value in _items(config):
        if key.endswith("_env") and isinstance(value, str):
            secret = environ.get(value)
            if secret and len(secret) >= _MIN_SECRET_LENGTH:
                secrets.add(secret)
                secrets.update(_lines(secret))
    for name in _DATABASE_URL_ENVS:
        password = _database_password(environ.get(name))
        if password and len(password) >= _MIN_SECRET_LENGTH:
            secrets.add(password)
    ordered = sorted(secrets, key=len, reverse=True)

    def redact_text(text: str) -> str:
        for secret in ordered:
            text = text.replace(secret, REDACTED)
        text = _URL_PASSWORD.sub(rf"\g<1>{REDACTED}", text)
        text = _KEY_VALUE.sub(rf"\g<1>{REDACTED}", text)
        return _BEARER.sub(rf"\g<1>{REDACTED}", text)

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, list):
            return [redact(v) for v in value]
        if isinstance(value, dict):
            return {
                k: REDACTED
                if isinstance(k, str) and k.lower() in _SECRET_KEYS and v is not None
                else redact(v)
                for k, v in value.items()
            }
        return value

    return redact


def _lines(secret: str) -> list[str]:
    """여러 줄인 비밀 값의 줄(앞뒤 공백 제외, 너무 짧은 줄 제외). 한 줄짜리 값이면 빈 목록."""
    if "\n" not in secret:
        return []
    return [s for line in secret.splitlines() if len(s := line.strip()) >= _MIN_SECRET_LENGTH]


def _items(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key), item
            yield from _items(item)
    elif isinstance(value, list):
        for item in value:
            yield from _items(item)


def _database_password(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return conninfo_to_dict(url).get("password")
    except Exception:  # 주소 모양이 아니면 가릴 비밀번호도 없다
        return None
