# src/pyholman/_clock/system.py
"""Production clock backed by system wall-clock and monotonic timer."""

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

__all__: list[str] = ['SystemClock']


@dataclass(frozen=True, slots=True)
class SystemClock:
    """
    Production clock backed by system wall-clock and monotonic timer.

    Returns timezone-aware UTC datetimes. This is the default clock for
    production use.
    """

    def now_utc(self) -> datetime:
        """Return current UTC time."""
        return datetime.now(tz=UTC)

    def today_utc(self) -> date:
        """Return current UTC date."""
        return self.now_utc().date()

    def monotonic_seconds(self) -> float:
        """Return monotonic time using ``time.perf_counter``."""
        return time.perf_counter()
