"""계약의 시각(UTC epoch 밀리초 정수)과 DB의 timestamptz(datetime)를 바꾼다."""

from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)


def to_datetime(ms: int) -> datetime:
    """epoch 밀리초 → UTC 시간대가 붙은 datetime."""
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise TypeError("epoch 밀리초는 정수여야 한다")
    return _EPOCH + timedelta(milliseconds=ms)


def to_epoch_ms(value: datetime) -> int:
    """시간대가 붙은 datetime → epoch 밀리초. 밀리초 아래 자리는 버린다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시간대가 없는 datetime은 바꿀 수 없다")
    return (value - _EPOCH) // _ONE_MS
