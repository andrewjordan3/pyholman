# tests/test_clock.py
"""Tests for the time-abstraction primitives in :mod:`pyholman._clock`."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Final

import pytest

from pyholman._clock import (
    Clock,
    FrozenClock,
    Stopwatch,
    SystemClock,
)

__all__: list[str] = []


_FROZEN_INSTANT: Final[datetime] = datetime(2026, 1, 23, 12, 0, 0, tzinfo=UTC)


# =============================================================================
# SystemClock
# =============================================================================


class TestSystemClock:
    def test_now_utc_is_timezone_aware_and_utc(self) -> None:
        clock: SystemClock = SystemClock()
        now: datetime = clock.now_utc()
        assert now.tzinfo is not None
        # ``datetime.now(tz=UTC)`` produces ``tzinfo`` that is the
        # ``UTC`` singleton; equality and identity both hold.
        assert now.utcoffset() == timedelta(0)

    def test_today_utc_matches_now_utc_date(self) -> None:
        clock: SystemClock = SystemClock()
        # Read ``now_utc`` first so the comparison can never fail under
        # a midnight-UTC race: ``today_utc`` is documented to be
        # ``now_utc().date()`` and the implementation calls it through.
        same_call_now: datetime = clock.now_utc()
        same_call_today: date = clock.today_utc()
        assert same_call_today == same_call_now.date()

    def test_monotonic_seconds_returns_non_negative_float(self) -> None:
        clock: SystemClock = SystemClock()
        first: float = clock.monotonic_seconds()
        assert isinstance(first, float)
        assert first >= 0.0

    def test_consecutive_monotonic_reads_are_non_decreasing(self) -> None:
        clock: SystemClock = SystemClock()
        first: float = clock.monotonic_seconds()
        second: float = clock.monotonic_seconds()
        assert second >= first


# =============================================================================
# FrozenClock — construction
# =============================================================================


class TestFrozenClockConstruction:
    def test_naive_start_time_raises(self) -> None:
        # ``noqa: DTZ001`` — the naive datetime is the test fixture: we
        # are exercising the rejection path.
        with pytest.raises(ValueError, match='timezone-aware'):
            FrozenClock(start_time_utc=datetime(2026, 1, 23, 12, 0, 0))  # noqa: DTZ001

    def test_non_utc_start_time_raises(self) -> None:
        # Build an offset-aware datetime that is not the ``UTC`` singleton.
        non_utc: timezone = timezone(timedelta(hours=5))
        with pytest.raises(ValueError, match=r'datetime\.UTC'):
            FrozenClock(start_time_utc=datetime(2026, 1, 23, 12, 0, 0, tzinfo=non_utc))

    def test_negative_start_monotonic_raises(self) -> None:
        with pytest.raises(ValueError, match='non-negative'):
            FrozenClock(
                start_time_utc=_FROZEN_INSTANT,
                start_monotonic_seconds=-1.0,
            )


# =============================================================================
# FrozenClock — frozen reads
# =============================================================================


class TestFrozenClockReads:
    def test_now_utc_returns_frozen_value(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        assert clock.now_utc() == _FROZEN_INSTANT
        # Two consecutive reads return the exact same instant — that is
        # the whole point of "frozen".
        assert clock.now_utc() == clock.now_utc()

    def test_today_utc_returns_frozen_date(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        assert clock.today_utc() == _FROZEN_INSTANT.date()

    def test_monotonic_seconds_returns_frozen_value(self) -> None:
        clock: FrozenClock = FrozenClock(
            start_time_utc=_FROZEN_INSTANT,
            start_monotonic_seconds=42.5,
        )
        assert clock.monotonic_seconds() == 42.5
        assert clock.monotonic_seconds() == 42.5

    def test_default_start_monotonic_is_zero(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        assert clock.monotonic_seconds() == 0.0


# =============================================================================
# FrozenClock — mutation
# =============================================================================


class TestFrozenClockAdvance:
    def test_advance_moves_both_wall_and_monotonic(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        delta: timedelta = timedelta(hours=1, seconds=30)

        clock.advance(delta)

        assert clock.now_utc() == _FROZEN_INSTANT + delta
        # The monotonic counter advances by the same number of seconds.
        assert clock.monotonic_seconds() == pytest.approx(delta.total_seconds())

    def test_advance_zero_is_noop(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        clock.advance(timedelta(0))
        assert clock.now_utc() == _FROZEN_INSTANT
        assert clock.monotonic_seconds() == 0.0

    def test_advance_negative_delta_raises(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        with pytest.raises(ValueError, match='non-negative'):
            clock.advance(timedelta(seconds=-1))

    def test_advance_is_cumulative(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        clock.advance(timedelta(seconds=10))
        clock.advance(timedelta(seconds=5))
        assert clock.now_utc() == _FROZEN_INSTANT + timedelta(seconds=15)
        assert clock.monotonic_seconds() == pytest.approx(15.0)


class TestFrozenClockSetTime:
    def test_set_time_updates_wall_only(self) -> None:
        clock: FrozenClock = FrozenClock(
            start_time_utc=_FROZEN_INSTANT,
            start_monotonic_seconds=100.0,
        )
        new_time: datetime = _FROZEN_INSTANT + timedelta(days=7)

        clock.set_time(new_time)

        assert clock.now_utc() == new_time
        # Monotonic counter is preserved by ``set_time``; only
        # ``advance`` keeps wall and monotonic in lockstep.
        assert clock.monotonic_seconds() == 100.0

    def test_set_time_naive_raises(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        # ``noqa: DTZ001`` — the naive datetime is the test fixture.
        with pytest.raises(ValueError, match='timezone-aware'):
            clock.set_time(datetime(2026, 6, 1, 12, 0, 0))  # noqa: DTZ001

    def test_set_time_non_utc_raises(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        non_utc: timezone = timezone(timedelta(hours=-5))
        with pytest.raises(ValueError, match=r'datetime\.UTC'):
            clock.set_time(datetime(2026, 6, 1, 12, 0, 0, tzinfo=non_utc))


# =============================================================================
# Stopwatch
# =============================================================================


class TestStopwatch:
    def test_start_captures_clock_monotonic(self) -> None:
        clock: FrozenClock = FrozenClock(
            start_time_utc=_FROZEN_INSTANT,
            start_monotonic_seconds=7.5,
        )
        stopwatch: Stopwatch = Stopwatch.start(clock=clock)
        assert stopwatch.start_monotonic_seconds == 7.5

    def test_elapsed_returns_difference(self) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        stopwatch: Stopwatch = Stopwatch.start(clock=clock)

        clock.advance(timedelta(seconds=2.5))
        assert stopwatch.elapsed_seconds(clock=clock) == pytest.approx(2.5)

    def test_two_stopwatches_against_same_clock_measure_independently(
        self,
    ) -> None:
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        first_stopwatch: Stopwatch = Stopwatch.start(clock=clock)

        clock.advance(timedelta(seconds=5))
        second_stopwatch: Stopwatch = Stopwatch.start(clock=clock)

        clock.advance(timedelta(seconds=3))
        # First stopwatch saw both advances; second saw only the second.
        assert first_stopwatch.elapsed_seconds(clock=clock) == pytest.approx(8.0)
        assert second_stopwatch.elapsed_seconds(clock=clock) == pytest.approx(3.0)


# =============================================================================
# Protocol satisfaction
# =============================================================================


class TestProtocolSatisfaction:
    """``Clock`` is ``runtime_checkable``; assert structural conformance
    of every concrete implementation."""

    def test_system_clock_satisfies_clock_protocol(self) -> None:
        assert isinstance(SystemClock(), Clock)

    def test_frozen_clock_satisfies_clock_protocol(self) -> None:
        assert isinstance(FrozenClock(start_time_utc=_FROZEN_INSTANT), Clock)
