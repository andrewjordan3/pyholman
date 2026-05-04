# src/pyholman/_clock/frozen.py
"""Deterministic clock for tests and reproducible runs."""

from datetime import UTC, date, datetime, timedelta

__all__: list[str] = ['FrozenClock']


class FrozenClock:
    """
    Deterministic clock for tests and reproducible runs.

    Starts at a fixed UTC datetime and only advances when explicitly
    mutated via :meth:`advance` or :meth:`set_time`.

    Attributes:
        _current_time_utc: The frozen wall-clock time.
        _current_monotonic_seconds: The frozen monotonic counter.

    Example:
        >>> clock = FrozenClock(start_time_utc=datetime(2026, 1, 23, 12, tzinfo=UTC))
        >>> clock.now_utc()
        datetime.datetime(2026, 1, 23, 12, 0, tzinfo=datetime.timezone.utc)
        >>> clock.advance(timedelta(hours=1))
        >>> clock.now_utc().hour
        13

    Note:
        Not thread-safe. Keep usage test-scoped or wrap externally.
    """

    __slots__ = ('_current_monotonic_seconds', '_current_time_utc')

    def __init__(
        self,
        *,
        start_time_utc: datetime,
        start_monotonic_seconds: float = 0.0,
    ) -> None:
        """
        Initialize a frozen clock.

        Args:
            start_time_utc: Initial time (must be timezone-aware UTC).
            start_monotonic_seconds: Initial monotonic value
                (non-negative).

        Raises:
            ValueError: If ``start_time_utc`` is naive or not UTC.
            ValueError: If ``start_monotonic_seconds`` is negative.
        """
        if start_time_utc.tzinfo is None:
            raise ValueError('start_time_utc must be timezone-aware (UTC).')
        if start_time_utc.tzinfo is not UTC:
            raise ValueError('start_time_utc must use datetime.UTC.')
        if start_monotonic_seconds < 0.0:
            raise ValueError('start_monotonic_seconds must be non-negative.')

        self._current_time_utc: datetime = start_time_utc
        self._current_monotonic_seconds: float = start_monotonic_seconds

    def now_utc(self) -> datetime:
        """Return the frozen UTC time."""
        return self._current_time_utc

    def today_utc(self) -> date:
        """Return the frozen UTC date."""
        return self._current_time_utc.date()

    def monotonic_seconds(self) -> float:
        """Return the frozen monotonic value."""
        return self._current_monotonic_seconds

    def advance(self, delta: timedelta) -> None:
        """
        Advance the clock by a duration.

        Args:
            delta: Time to advance (must be non-negative).

        Raises:
            ValueError: If ``delta`` is negative.

        Side Effects:
            Updates both the wall-clock and monotonic counters by
            ``delta``; the two stay in lockstep.
        """
        if delta.total_seconds() < 0:
            raise ValueError('delta must be non-negative.')

        self._current_time_utc += delta
        self._current_monotonic_seconds += delta.total_seconds()

    def set_time(self, new_time_utc: datetime) -> None:
        """
        Set the clock to a specific UTC time.

        Does not adjust the monotonic counter — use :meth:`advance` for
        correlated wall/monotonic changes.

        Args:
            new_time_utc: New time (must be timezone-aware UTC).

        Raises:
            ValueError: If ``new_time_utc`` is naive or not UTC.

        Side Effects:
            Updates the wall-clock counter only; the monotonic counter
            is unchanged.
        """
        if new_time_utc.tzinfo is None:
            raise ValueError('new_time_utc must be timezone-aware (UTC).')
        if new_time_utc.tzinfo is not UTC:
            raise ValueError('new_time_utc must use datetime.UTC.')

        self._current_time_utc = new_time_utc
