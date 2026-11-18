"""매핑표가 이름으로 부르는 작은 변환의 등록부(D-061). 표에는 조건식이나 스크립트를 넣지 않는다.

변환마다 받을 수 있는 값(accepts)과 내보낼 수 있는 값의 집합(values, 선택)을 선언한다.
values는 검증기가 target의 enum과 맞는지 볼 때 쓴다.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from soc.contracts import to_epoch_ms
from soc.normalize.errors import NormalizeError

SEVERITY_IDS = {"low": 2, "medium": 3, "high": 4, "critical": 5}


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


# 변환을 정하지 않은 항목이 쓴다. 문자열을 그대로 옮긴다
COPY = Transform(lambda value: value)

TRANSFORMS: dict[str, Transform] = {
    "time": Transform(_time),
    "severity": Transform(
        SEVERITY_IDS.get, values=frozenset(str(value) for value in SEVERITY_IDS.values())
    ),
    "round_int": Transform(_round_int, accepts=lambda value: value is not None),
}
