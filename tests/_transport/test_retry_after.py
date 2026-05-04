# tests/_transport/test_retry_after.py
"""Tests for the ``Retry-After`` header parser."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from pyholman._clock import FrozenClock, SystemClock
from pyholman._transport import parse_retry_after_header

__all__: list[str] = []


_FROZEN_NOW: datetime = datetime(2026, 1, 23, 12, 0, 0, tzinfo=UTC)


def _http_date(target: datetime) -> str:
    """Render ``target`` as an RFC 7231 IMF-fixdate string."""
    return format_datetime(target, usegmt=True)


class TestDeltaSeconds:
    def test_positive_integer(self) -> None:
        # Delta-seconds parsing does not consult the clock, but the
        # signature still requires one — pass a real clock so the
        # contract is exercised end-to-end.
        assert parse_retry_after_header('120', clock=SystemClock()) == 120.0

    def test_zero(self) -> None:
        assert parse_retry_after_header('0', clock=SystemClock()) == 0.0

    def test_negative_integer_returns_zero(self) -> None:
        assert parse_retry_after_header('-5', clock=SystemClock()) == 0.0

    def test_whitespace_around_integer_is_tolerated(self) -> None:
        assert parse_retry_after_header('  60  ', clock=SystemClock()) == 60.0


class TestHttpDate:
    def test_future_date_returns_exact_seconds_until_then(self) -> None:
        future_offset_seconds: int = 30
        future_target: datetime = _FROZEN_NOW + timedelta(seconds=future_offset_seconds)
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_NOW)

        wait_seconds: float = parse_retry_after_header(
            _http_date(future_target), clock=clock
        )

        # IMF-fixdate has second-level granularity, so the round-trip
        # is exact — no tolerance needed when the clock is frozen.
        assert wait_seconds == float(future_offset_seconds)

    def test_past_date_returns_zero(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_NOW)
        past_target: datetime = _FROZEN_NOW - timedelta(minutes=5)
        assert parse_retry_after_header(_http_date(past_target), clock=clock) == 0.0


class TestUnparseableInput:
    def test_garbage_returns_zero(self) -> None:
        assert (
            parse_retry_after_header('not a header value at all', clock=SystemClock())
            == 0.0
        )

    def test_none_returns_zero(self) -> None:
        assert parse_retry_after_header(None, clock=SystemClock()) == 0.0

    def test_empty_string_returns_zero(self) -> None:
        assert parse_retry_after_header('', clock=SystemClock()) == 0.0

    def test_whitespace_only_returns_zero(self) -> None:
        assert parse_retry_after_header('   ', clock=SystemClock()) == 0.0
