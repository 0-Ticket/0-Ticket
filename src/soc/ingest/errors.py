"""수집 대상 하나의 실행을 멈추는 오류."""

# 실패 기록(stderr, 체크포인트의 last_error)에는 대상 이름과 이 종류만 남긴다.
# 응답 본문, 원본 문서, 주소, 인증 값은 넣지 않는다.
FAILURES = (
    "timeout",
    "too_large",
    "http_status",
    "network",
    "auth",
    "response_shape",
    "contract_rejected",
    "db_error",
)


class IngestError(Exception):
    """ELK에서 페이지를 받지 못했거나 응답이 기대한 모양이 아니다. kind는 FAILURES 중 하나다.

    contract_rejected와 db_error는 저장 단계(ContractError, psycopg.Error)에서 run이 붙인다.
    """

    def __init__(self, kind: str) -> None:
        if kind not in FAILURES:
            raise ValueError(f"알 수 없는 실패 종류: {kind}")
        super().__init__(kind)
        self.kind = kind
