"""설정에 적힌 주소 하나를 가져온다(HTTP 클라이언트 httpx, D-039).

- 리다이렉트는 따라가지 않는다. 2xx가 아니면(3xx 포함) http_status.
- 응답은 스트리밍으로 받으며 압축을 푼 뒤의 바이트를 세고, 상한을 넘으면 그 자리에서 끊는다.
  Content-Length는 믿지 않는다.
- 요청 단위 timeout(클라이언트 설정)과 별도로, 조각을 받을 때마다 전체 마감 시간을 확인한다.
"""

import time
from collections.abc import Callable

import httpx

from soc.l3.intel.errors import IntelError


def fetch(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int,
    deadline_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    started = clock()
    body = bytearray()
    try:
        with client.stream("GET", url, follow_redirects=False) as response:
            if not 200 <= response.status_code < 300:
                raise IntelError("http_status")
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise IntelError("too_large")
                if clock() - started > deadline_seconds:
                    raise IntelError("timeout")
    except httpx.TimeoutException:
        raise IntelError("timeout") from None
    except httpx.HTTPError:
        # 연결 실패, 프로토콜 오류, 압축 해제 오류 등. 예외 메시지는 남기지 않는다.
        raise IntelError("network") from None
    return bytes(body)
