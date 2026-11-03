"""계약 시각(UTC epoch 밀리초) ↔ DB 시각(timestamptz) 변환."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from soc.contracts import to_datetime, to_epoch_ms

KST = timezone(timedelta(hours=9))


def test_to_datetime_returns_utc() -> None:
    assert to_datetime(1793678580123) == datetime(2026, 11, 3, 4, 3, 0, 123000, tzinfo=UTC)
    assert to_datetime(1793678580123).tzinfo is UTC


@pytest.mark.parametrize("ms", [0, 1, 1793678578000, 1793678580123, 1793678580999])
def test_round_trip_keeps_value(ms: int) -> None:
    assert to_epoch_ms(to_datetime(ms)) == ms


def test_other_time_zone_is_converted() -> None:
    assert to_epoch_ms(datetime(2026, 11, 3, 13, 3, 0, 123000, tzinfo=KST)) == 1793678580123


def test_below_millisecond_is_dropped() -> None:
    assert to_epoch_ms(datetime(2026, 11, 3, 4, 3, 0, 123999, tzinfo=UTC)) == 1793678580123


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        to_epoch_ms(datetime(2026, 11, 3, 4, 3, 0))


@pytest.mark.parametrize("value", [1.5, "1793678580123", True])
def test_non_integer_milliseconds_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        to_datetime(value)  # type: ignore[arg-type]
