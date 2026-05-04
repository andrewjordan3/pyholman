# src/pyholman/_clock/stopwatch.py
"""Elapsed-time measurement using monotonic time."""

from dataclasses import dataclass
from typing import Self

from pyholman._clock.protocol import Clock

__all__: list[str] = ['Stopwatch']


@dataclass(frozen=True, slots=True)
class Stopwatch:
    """
    Elapsed-time measurement using monotonic time.

    Safer than wall-clock time for durations since monotonic time is
    unaffected by system clock adjustments.

    Attributes:
        start_monotonic_seconds: Monotonic timestamp when started.

    Example:
        >>> stopwatch = Stopwatch.start(clock=system_clock)
        >>> # ... work ...
        >>> elapsed = stopwatch.elapsed_seconds(clock=system_clock)

    Note:
        Use the same clock instance for ``start`` and the ``elapsed``
        measurement.
    """

    start_monotonic_seconds: float

    @classmethod
    def start(cls, *, clock: Clock) -> Self:
        """
        Create and start a stopwatch.

        Args:
            clock: Clock providing :meth:`Clock.monotonic_seconds`.

        Returns:
            A started :class:`Stopwatch` instance.
        """
        return cls(start_monotonic_seconds=clock.monotonic_seconds())

    def elapsed_seconds(self, *, clock: Clock) -> float:
        """
        Compute elapsed seconds since start.

        Args:
            clock: Clock providing :meth:`Clock.monotonic_seconds`.

        Returns:
            Elapsed time in seconds.
        """
        return clock.monotonic_seconds() - self.start_monotonic_seconds
