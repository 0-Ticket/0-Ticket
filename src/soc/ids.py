"""데이터 ID: 접두사 + UUIDv7(RFC 9562) 문자열.

UUIDv7은 앞 48비트가 밀리초 시각이라 문자열로 정렬하면 만든 순서가 된다.
같은 밀리초 안에서도 순서가 지켜지게 rand_a 12비트를 카운터로 쓴다(RFC 9562 6.2 Method 1).
순서 보장은 한 프로세스 안에서만이고, 프로세스끼리는 밀리초 단위까지 맞는다.
Python 3.13 표준 라이브러리에 UUIDv7이 없어 직접 구현한다(ID 생성, D-034).
"""

import secrets
import threading
import time

# 접두사 목록의 기준. contracts/common/types.schema.json의 ID 정의와 맞춘다.
PREFIXES = (
    "raw",
    "alt",
    "evt",
    "tkt",
    "inc",
    "art",
    "prp",
    "cas",
    "agl",
    "run",
    "hnt",
    "hrn",
)

_COUNTER_MAX = 0xFFF
_lock = threading.Lock()
_last_ms = -1
_counter = 0


def new_id(prefix: str) -> str:
    """`new_id("tkt")` → `tkt_0192f3c5-7b2e-7a10-9c3d-1f2e3a4b5c6d`."""
    if prefix not in PREFIXES:
        raise ValueError(f"알 수 없는 ID 접두사다. 쓸 수 있는 값: {', '.join(PREFIXES)}")
    return f"{prefix}_{_uuid7()}"


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _next_timestamp_and_counter() -> tuple[int, int]:
    global _last_ms, _counter
    with _lock:
        now = _now_ms()
        if now > _last_ms:
            _last_ms = now
            # 카운터 시작값은 아래 절반에서 무작위로 고른다.
            # 같은 밀리초에 2048번 이상 더 만들 수 있다.
            _counter = secrets.randbits(11)
        else:
            # 같은 밀리초이거나 시계가 뒤로 갔다. 마지막 시각을 유지하고 카운터를 올린다.
            _counter += 1
            if _counter > _COUNTER_MAX:
                _last_ms += 1
                _counter = secrets.randbits(11)
        return _last_ms, _counter


def _uuid7() -> str:
    unix_ms, counter = _next_timestamp_and_counter()
    value = (
        (unix_ms & 0xFFFF_FFFF_FFFF) << 80  # unix_ts_ms 48비트
        | 0x7 << 76  # version 7
        | counter << 64  # rand_a 12비트(카운터)
        | 0b10 << 62  # variant
        | secrets.randbits(62)  # rand_b
    )
    h = f"{value:032x}"
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
