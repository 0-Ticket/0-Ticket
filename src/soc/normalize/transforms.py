"""매핑표가 이름으로 부르는 작은 변환의 등록부(D-061). 표에는 조건식이나 스크립트를 넣지 않는다.

변환마다 받을 수 있는 값(accepts)과 내보낼 수 있는 값의 집합(values, 선택)을 선언한다.
values는 검증기가 target의 enum과 맞는지 볼 때 쓴다.
"""

import ipaddress
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from soc.contracts import to_epoch_ms
from soc.normalize.errors import NormalizeError

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
_MAX_DIGITS = 9
_MONTHS = {
    name: number
    for number, name in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)
}
_CTIME = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Za-z]{3}) ( ?[0-9]|[0-9]{2}) "
    r"([0-9]{2}):([0-9]{2}):([0-9]{2}) ([0-9]{4})"
)


def is_text(value: Any) -> bool:
    """비어 있지 않은 문자열인가. 변환을 정하지 않은 항목이 받는 값이다."""
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class Transform:
    """등록된 변환 하나.

    Attributes:
        convert: 값을 바꾼다. None을 돌려주면 값 없음(누락)이다. 읽을 수 없으면 NormalizeError.
        accepts: `from`에서 "있는 값"으로 칠 값. 거르는 값은 다음 경로로 넘어간다.
        values: 내보낼 수 있는 값의 집합(문자열로). 정하지 않으면 enum 검사를 하지 않는다.
    """

    convert: Callable[[Any], Any]
    accepts: Callable[[Any], bool] = is_text
    values: frozenset[str] | None = None


def _time(value: str) -> int:
    """시간대가 있는 ISO 8601 문자열을 UTC epoch 밀리초로 바꾼다."""
    try:
        return to_epoch_ms(datetime.fromisoformat(value))
    except ValueError:
        raise NormalizeError("validation_failed") from None


def _round_int(value: Any) -> int | None:
    """유한한 숫자를 반올림한 정수로 바꾼다. 그 밖은 None."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(value)


def _http_method(value: str) -> str | None:
    method = value.upper()
    return method if method in HTTP_ACTIVITY_IDS else None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= _MAX_DIGITS:
        return int(value)
    return None


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _geo_coordinates(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    lon, lat = value.get("lon"), value.get("lat")
    return [lon, lat] if _finite_number(lon) and _finite_number(lat) else None


def _ctime_utc(value: Any) -> int:
    match = _CTIME.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise NormalizeError("validation_failed")
    month_name, day, hour, minute, second, year = match.groups()
    try:
        return to_epoch_ms(
            datetime(
                int(year),
                _MONTHS[month_name],
                int(day),
                int(hour),
                int(minute),
                int(second),
                tzinfo=UTC,
            )
        )
    except (KeyError, ValueError):
        raise NormalizeError("validation_failed") from None


def _present(value: Any) -> bool:
    return value is not None


# 변환을 정하지 않은 항목이 쓴다. 문자열을 그대로 옮긴다
COPY = Transform(lambda value: value)

TRANSFORMS: dict[str, Transform] = {
    "time": Transform(_time),
    "severity": Transform(
        SEVERITY_IDS.get, values=frozenset(str(value) for value in SEVERITY_IDS.values())
    ),
    "round_int": Transform(_round_int, accepts=lambda value: value is not None),
    "http_method": Transform(_http_method, values=frozenset(HTTP_ACTIVITY_IDS)),
    "method_name": Transform(str.upper),
    "to_int": Transform(_to_int, accepts=_present),
    "geo_coordinates": Transform(_geo_coordinates, accepts=_present),
    "ctime_utc": Transform(_ctime_utc, accepts=_present),
}


# host:port, [v6]:port, [v6]. 맨 IPv6(콜론 여러 개)는 맞지 않는다
_HOST_PORT = re.compile(r"\[([^\]]+)\](?::\d{1,5})?|([^:\[\]]+):\d{1,5}")


def is_ip(value: str) -> bool:
    """IPv4·IPv6 형식이면 True.

    Args:
        value: 검사할 문자열.
    """
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def strip_port(value: str) -> str:
    """host:port, [v6]:port, [v6]에서 포트와 대괄호를 뗀다. 맨 IPv6는 그대로 둔다.

    Args:
        value: domain 후보 값.
    """
    match = _HOST_PORT.fullmatch(value)
    return (match.group(1) or match.group(2)) if match else value


@dataclass(frozen=True)
class EntityTransform:
    """엔티티 항목의 변환. `entries` 변환과 따로 등록한다(D-062).

    Attributes:
        convert: (선언한 type, 원본 문자열)을 받아 (type, 값)을 돌려준다.
            읽을 수 없으면 NormalizeError.
    """

    convert: Callable[[str, str], tuple[str, str]]


def _ip(entity_type: str, value: str) -> tuple[str, str]:
    """IP 형식만 받는다."""
    if not is_ip(value):
        raise NormalizeError("validation_failed")
    return entity_type, value


def _domain_or_ip(_entity_type: str, value: str) -> tuple[str, str]:
    """포트를 떼고 IP 형식이면 type을 ip로, 아니면 domain으로 한다."""
    host = strip_port(value)
    return ("ip" if is_ip(host) else "domain"), host


ENTITY_TRANSFORMS: dict[str, EntityTransform] = {
    "ip": EntityTransform(_ip),
    "domain_or_ip": EntityTransform(_domain_or_ip),
}
