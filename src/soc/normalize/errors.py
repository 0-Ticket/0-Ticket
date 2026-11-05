"""정규화 실패 코드. 상태 테이블에는 코드만 남기고 원문 예외 메시지는 남기지 않는다."""

FAILURES = ("validation_failed", "schema_failed", "asset_lookup_failed", "db_error")


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
