# src/pyholman/_clock/protocol.py
"""
Clock Protocol — interface for time providers.

Centralizing time access avoids scattered ``datetime.now()`` calls and
enables deterministic time in tests. All implementations must return
timezone-aware UTC datetimes.
"""

from datetime import date, datetime
from typing import Protocol, runtime_checkable

__all__: list[str] = ['Clock']


@runtime_checkable
class Clock(Protocol):
    """
    Interface for time providers.

    Design Goals:
        - Centralize time access (no scattered ``datetime.now()`` calls).
        - Enable deterministic time in tests.
        - Enforce timezone-aware UTC timestamps internally.

    All implementations must return timezone-aware UTC datetimes.
    """

    def now_utc(self) -> datetime:
        """
        Return the current time as a timezone-aware UTC datetime.

        Returns:
            Timezone-aware datetime in UTC.
        """
        ...

    def today_utc(self) -> date:
        """
        Return today's date in UTC.

        Returns:
            Current UTC date.
        """
        ...

    def monotonic_seconds(self) -> float:
        """
        Return a monotonic timestamp for duration measurement.

        Monotonic clocks are unaffected by NTP adjustments or DST changes,
        making them suitable for measuring elapsed time.

        Returns:
            Monotonic time in seconds.
        """
        ...
