"""비밀 값을 [REDACTED]로 가린다. 외부 LLM 입력(D-048, #279)과 Agent Log 쓰기 직전에 쓴다.

입출력에 비밀 값을 넣지 않는 것이 먼저다. 이 함수는 그래도 섞여 든 값을 한 번 더 지운다.
같은 입력에는 항상 같은 결과를 내고(상태 없음), 이미 가린 문자열에 다시 써도 같다(멱등).
JSON 값(dict·list·str·숫자·불리언·None)만 받는다. 그 밖의 타입은 TypeError다. 가리지 못한 채
통과시키지 않고, 부르는 쪽이 보내지 않는다(fail-closed).
가리는 것은 세 가지다.
1. 설정의 *_env가 가리키는 환경변수의 실제 값(8자 이상. 더 짧은 값은 평범한 낱말까지 지운다).
   모델에게 가는 도구 결과는 JSON 문자열이라 ", \\, <, >가 이스케이프되므로(registry._dump)
   이스케이프된 모양도 함께 가린다. 여러 줄인 값(SSH 개인 키, #213)은 값 전체와 함께 줄마다
   가린다. 근거 ID 모양(접두사 + UUIDv7)은 이 치환에서만 건너뛴다.
2. DB 주소(DATABASE_URL, AGENT_DATABASE_URL)의 비밀번호, 그리고 문자열 속 URL의 비밀번호 자리
3. password=·token=·secret=·api_key 모양의 값, Authorization: Bearer|Basic|ApiKey, 그리고 이름이
   password·api_key·token·secret 등인 객체 키(JSON 문자열 속의 "키": "값" 모양 포함)의 값.
   pwd=는 값이 /로 시작하는 두 단계 이상 경로(sudo의 PWD=/home/alice)면 건너뛴다.

모델에게 가는 문자열 중 <태그>\\nJSON\\n</태그> 모양(registry의 도구 결과, runner.wrap_data의 입력
데이터)은 JSON으로 풀어 dict 규칙(객체·배열·숫자 값 아래의 비밀 키)으로 가린다. 가림으로 바뀐
것이 없으면 원문 문자열을 그대로 두고, 풀리지 않으면 문자열 규칙만 쓴다.
"""

import json
import os
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from psycopg.conninfo import conninfo_to_dict

from soc.ids import PREFIXES

REDACTED = "[REDACTED]"

# 너무 짧은 값은 평범한 낱말까지 지우므로 가리지 않는다(8자 미만 비밀은 못 가린다. security.md).
_MIN_SECRET_LENGTH = 8
_DATABASE_URL_ENVS = ("DATABASE_URL", "AGENT_DATABASE_URL")
_SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "api_key",
        "apikey",
        "api-key",
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "client_secret",
    }
)

# 근거 ID(접두사 + UUIDv7). split의 홀수 칸이 되도록 묶음 하나로 감싼다
_ID = re.compile(
    r"\b((?:" + "|".join(PREFIXES) + r")_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}"
    r"-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b"
)
# <태그>\nJSON\n</태그>. 태그 이름은 registry(tool_result)와 runner(data)가 정한다
_ENVELOPE = re.compile(r"<(?P<tag>[a-z_]+)>\n(?P<body>.*)\n</(?P=tag)>", re.DOTALL)
# 낱말 길이·개수를 제한한다. 제한이 없으면 -·_로 이어진 긴 글에서 이차 시간이 된다(#292 리뷰)
_PREFIX_WORDS = r"(?:[A-Za-z0-9]{1,32}[_-]){0,4}"
# 스킴 길이 제한도 같은 이유다
_URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]{0,31}://[^\s:/@]+:)[^\s@/]+(?=@)", re.IGNORECASE)
# "키": "값" 모양(JSON 문자열). 객체 키 규칙과 같은 이름의 값을 닫는 따옴표 앞까지 가린다.
_JSON_SECRET_KEY = re.compile(
    r'("(?:' + "|".join(re.escape(k) for k in sorted(_SECRET_KEYS)) + r')"\s*:\s*")(?:[^"\\]|\\.)*',
    re.IGNORECASE,
)
_ASSIGN = r"[\"']?\s*[:=]\s*[\"']?"
_VALUE = r"[^\s\"',;&}]+"
_KEY_VALUE = re.compile(
    r"(\b(?:password|passwd|api[_-]?key)" + _ASSIGN + r")" + _VALUE, re.IGNORECASE
)
# 이름이 token·secret으로 끝나는 낱말(access_token, client_secret, refresh-token). tokenizer 제외
_NAMED_SECRET = re.compile(
    r"((?<![A-Za-z0-9])(?P<name>" + _PREFIX_WORDS + r"(?:token|secret))" + _ASSIGN + r")" + _VALUE,
    re.IGNORECASE,
)
# 비밀이 아닌 페이지 이동 표지(next_token, page_token, next_page_token, continuation_token)
_CURSOR_NAME = re.compile(r"(?:next|prev|previous|continuation|page)(?:[_-]page)?[_-]token", re.I)
# sudo의 PWD=/home/alice처럼 /로 시작하는 경로 두 단계 이상이면 건너뛴다. /Secret99와 /a 한 단계는
# 가리고, /a/b 모양 비밀번호는 못 가린다(한계, security.md)
_PWD = re.compile(
    r"(\bpwd" + _ASSIGN + r")(?!/[^/\s\"',;&}]+/[^/\s\"',;&}]+)" + _VALUE, re.IGNORECASE
)
_BEARER = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_AUTH_SCHEME = re.compile(
    r"(\bAuthorization[\"']?\s*[:=]\s*[\"']?(?:Basic|ApiKey)\s+)[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
# 순서가 있다: JSON 키 규칙이 값 전체를 먼저 가리고, 나머지는 남은 모양을 가린다
_PATTERNS = (
    _URL_PASSWORD,
    _JSON_SECRET_KEY,
    _KEY_VALUE,
    _NAMED_SECRET,
    _PWD,
    _BEARER,
    _AUTH_SCHEME,
)


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
    for secret in list(secrets):
        secrets.update(_json_forms(secret))
    ordered = sorted(secrets, key=len, reverse=True)

    def replace_secrets(text: str) -> str:
        parts = _ID.split(text)  # 홀수 칸은 근거 ID라 이 치환에서 건너뛴다
        for i in range(0, len(parts), 2):
            for secret in ordered:
                parts[i] = parts[i].replace(secret, REDACTED)
        return "".join(parts)

    def redact_plain(text: str) -> str:
        text = replace_secrets(text)
        for pattern in _PATTERNS:
            text = pattern.sub(_mask, text)
        return text

    def redact_text(text: str) -> str:
        match = _ENVELOPE.fullmatch(text)
        if match is not None:
            try:
                data = json.loads(match["body"])
            except ValueError:
                data = None  # 잘린 결과 등. 문자열 규칙만 쓴다
            else:
                redacted = redact(data)
                if redacted != data:  # 바뀐 것만 다시 직렬화한다. 아니면 원문 그대로
                    text = _envelope(match["tag"], redacted)
        return redact_plain(text)

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
        if value is None or isinstance(value, bool | int | float):
            return value
        raise TypeError(f"가릴 수 없는 타입이다: {type(value).__name__}")

    return redact


def _envelope(tag: str, value: Any) -> str:
    """registry._dump·runner.wrap_data와 같은 직렬화(ensure_ascii=False, <·> 이스케이프)."""
    body = json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<{tag}>\n{body}\n</{tag}>"


def _json_forms(secret: str) -> set[str]:
    """JSON 문자열 속에서 보이는 모양: 이스케이프만, 그리고 <·>까지 이스케이프한 것."""
    escaped = json.dumps(secret, ensure_ascii=False)[1:-1]
    angled = escaped.replace("<", "\\u003c").replace(">", "\\u003e")
    return {escaped, angled}


def _mask(match: re.Match[str]) -> str:
    """묶음 1(키 부분)은 두고 그 뒤 값만 가린다. 페이지 이동 표지는 그대로 둔다."""
    name = match.groupdict().get("name")
    if name is not None and _CURSOR_NAME.fullmatch(name):
        return match.group(0)
    return f"{match.group(1)}{REDACTED}"


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
