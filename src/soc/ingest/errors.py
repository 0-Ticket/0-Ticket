"""수집 대상 하나의 실행을 멈추는 오류."""

# 실패 기록(stderr, 실행 이력의 outcome)에는 대상 이름과 이 종류만 남긴다.
# 응답 본문, 원본 문서, 주소, 인증 값은 넣지 않는다.
FAILURES = (
    "timeout",
    "too_large",
    "http_status",
    "network",
    "auth",
    "response_shape",
    "sort_value",
    "checkpoint_cursor",
    "contract_rejected",
    "db_error",
)


class IngestError(Exception):
    """ELK에서 페이지를 받지 못했거나 응답이 기대한 모양이 아니다.

    속성:
        kind: 실패 종류 코드. FAILURES 중 하나다.

    contract_rejected와 db_error는 이 클래스를 거치지 않고 run.py가 직접 kind에 넣는다.
    둘 다 FAILURES에 들어 있다.
    """

    def __init__(self, kind: str, *, retryable: bool = False) -> None:
        """인자 kind는 FAILURES 중 하나여야 한다. 아니면 ValueError."""
        if kind not in FAILURES:
            raise ValueError(f"알 수 없는 실패 종류: {kind}")
        super().__init__(kind)
        self.kind = kind
        self.retryable = retryable
