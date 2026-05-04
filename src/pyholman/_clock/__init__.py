# src/pyholman/_clock/__init__.py
"""
Time abstraction utilities.

Provides injectable clock interfaces to avoid scattered ``datetime.now()``
calls and enable deterministic time in tests.

Classes:
    Clock: Protocol defining the time provider interface.
    SystemClock: Production clock using system time.
    FrozenClock: Test clock fixed at a specific moment.
    Stopwatch: Monotonic duration measurement.

Example:
    >>> clock = SystemClock()
    >>> stopwatch = Stopwatch.start(clock=clock)
    >>> # ... work ...
    >>> elapsed = stopwatch.elapsed_seconds(clock=clock)
"""

from pyholman._clock.frozen import FrozenClock
from pyholman._clock.protocol import Clock
from pyholman._clock.stopwatch import Stopwatch
from pyholman._clock.system import SystemClock

__all__: list[str] = [
    'Clock',
    'FrozenClock',
    'Stopwatch',
    'SystemClock',
]
