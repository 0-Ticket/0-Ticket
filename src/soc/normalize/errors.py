"""정규화 실패 코드. 상태 테이블에는 코드만 남기고 원문 예외 메시지는 남기지 않는다."""

FAILURES = (
    "validation_failed",
    "schema_failed",
    "asset_lookup_failed",
    "db_error",
    "escape_collision",
)

# 결과는 저장하되 품질이 낮을 때의 사유. 상태(status)가 아니라 outcome이 구분 기준이다(#326)
PARTIAL_REASONS = ("unknown_source",)
FALLBACK_REASONS = (
    "invalid_source",
    "missing_uid",
    "missing_title",
    "bad_time",
    "validation_failed",
)
# 이벤트의 사유(#351). 알럿 목록과 따로 둔다
EVENT_PARTIAL_REASONS = ("missing_request_time_used_at_timestamp",)
EVENT_FALLBACK_REASONS = ("unsupported_event_mapping",)


class NormalizeError(Exception):
    """원본 한 건의 정규화가 실패했다.

    Attributes:
        code: FAILURES 중 하나.
    """

    def __init__(self, code: str) -> None:
        """실패 코드를 가진 정규화 예외를 만든다.

        Args:
            code: FAILURES에 정의된 실패 코드.
        """
        if code not in FAILURES:
            raise ValueError(f"알 수 없는 실패 코드: {code}")
        super().__init__(code)
        self.code = code
