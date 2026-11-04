"""출처 하나를 실패로 만드는 오류."""

# 실패 기록에는 출처 이름과 이 종류만 남긴다. 응답 본문은 넣지 않는다.
FAILURES = (
    "timeout",
    "too_large",
    "http_status",
    "network",
    "doctype",
    "parse",
    "version_mismatch",
)


class IntelError(Exception):
    """출처 하나를 가져오거나 읽지 못했다. kind는 FAILURES 중 하나다."""

    def __init__(self, kind: str) -> None:
        if kind not in FAILURES:
            raise ValueError(f"알 수 없는 실패 종류: {kind}")
        super().__init__(kind)
        self.kind = kind
