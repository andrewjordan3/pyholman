# src/pyholman/_transport/retry_after.py
"""
Parser for the HTTP ``Retry-After`` response header.

`RFC 9110 §10.2.3 <https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3>`_
defines two on-the-wire forms for ``Retry-After``:

    1. **Delta-seconds** — a non-negative integer count of seconds, e.g. ``120``.
    2. **HTTP-date** — an RFC 7231 IMF-fixdate like
       ``Wed, 21 Oct 2026 07:28:00 GMT``.

This module exposes a single function that accepts either form (or no
header at all) and returns a wait duration in seconds. The output type is
``float`` so callers can pass it straight into ``time.sleep`` or feed it
to the retry decorator's wait strategy without further conversion.

The function is deliberately lenient: any unparseable input — empty
string, garbage text, an HTTP-date already in the past — collapses to
``0.0``. The ``0.0`` sentinel matches the existing
:class:`pyholman._transport.RateLimitError.retry_after_seconds` contract:
zero means "no server guidance, fall back to exponential backoff."
Treating bad input as "no guidance" rather than raising keeps the rest
of the request pipeline simple — the caller never has to wrap
``parse_retry_after_header`` in a ``try/except`` to handle a server
that emits a malformed header.
"""

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from pyholman._clock import Clock

__all__: list[str] = ['parse_retry_after_header']

logger: logging.Logger = logging.getLogger(__name__)


def parse_retry_after_header(header_value: str | None, *, clock: Clock) -> float:
    """
    Parse a ``Retry-After`` header value into a non-negative wait in seconds.

    Accepts either of the two forms permitted by RFC 9110 §10.2.3:

        - **Delta-seconds**: a non-negative integer literal, e.g. ``"120"``
          → ``120.0``.
        - **HTTP-date**: an RFC 7231 IMF-fixdate, e.g.
          ``"Wed, 21 Oct 2026 07:28:00 GMT"`` → the number of seconds from
          ``clock.now_utc()`` to that instant. Already-past dates clamp to
          ``0.0``.

    Any input that cannot be interpreted as one of those two forms
    collapses to ``0.0``. The collapse happens for:

        - ``None`` (header absent on the response).
        - The empty string.
        - A negative delta-seconds value (RFC violation; the spec
          requires a non-negative integer).
        - A token that parses as neither an integer nor a recognized
          HTTP-date.
        - A valid HTTP-date that is already in the past.

    Args:
        header_value: Raw ``Retry-After`` header value, or ``None`` if
            the response did not include the header.
        clock: Time provider used to compute "seconds from now" for the
            HTTP-date branch. Required keyword-only so a deterministic
            :class:`~pyholman._clock.FrozenClock` can be threaded
            through from a test, replacing the wall-clock tolerance the
            previous (clock-less) implementation forced on callers.

    Returns:
        A non-negative wait duration in seconds. ``0.0`` indicates
        "no usable server guidance" — callers should fall back to
        their default backoff strategy in that case.
    """
    if header_value is None:
        return 0.0

    stripped_value: str = header_value.strip()
    if not stripped_value:
        return 0.0

    delta_seconds: float | None = _parse_delta_seconds(stripped_value)
    if delta_seconds is not None:
        return delta_seconds

    return _parse_http_date_to_wait_seconds(stripped_value, clock=clock)


def _parse_delta_seconds(header_value: str) -> float | None:
    """
    Try to interpret ``header_value`` as a non-negative integer delta-seconds.

    Args:
        header_value: A pre-stripped ``Retry-After`` value.

    Returns:
        The non-negative wait in seconds when ``header_value`` is an
        integer literal of zero or more. Returns ``None`` when the value
        is not an integer at all (so the caller can try the HTTP-date
        path). Returns ``0.0`` for negative integers — those are an RFC
        violation and we treat them as "no guidance."
    """
    try:
        delta_seconds: int = int(header_value)
    except ValueError:
        return None

    if delta_seconds < 0:
        logger.debug(
            'Retry-After delta-seconds is negative (%d); treating as no guidance.',
            delta_seconds,
        )
        return 0.0

    return float(delta_seconds)


def _parse_http_date_to_wait_seconds(header_value: str, *, clock: Clock) -> float:
    """
    Interpret ``header_value`` as an RFC 7231 HTTP-date and return the
    seconds remaining until that instant.

    Past dates clamp to ``0.0``, as do values that ``email.utils``
    cannot parse. The standard library's ``parsedate_to_datetime``
    handles all three HTTP-date forms (IMF-fixdate, RFC 850, ANSI C
    asctime) and returns a timezone-aware datetime; values that lack
    a timezone are treated as UTC, matching the RFC's requirement that
    HTTP-dates be in GMT.

    Args:
        header_value: A pre-stripped ``Retry-After`` value that already
            failed delta-seconds parsing.
        clock: Time provider whose ``now_utc()`` is the reference
            instant for the "seconds remaining" subtraction.

    Returns:
        Non-negative seconds from ``clock.now_utc()`` to the parsed
        instant. ``0.0`` if the value is unparseable or already in the
        past.
    """
    try:
        target_datetime: datetime = parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        logger.debug(
            'Retry-After value %r is neither delta-seconds nor a recognized '
            'HTTP-date; treating as no guidance.',
            header_value,
        )
        return 0.0

    if target_datetime.tzinfo is None:
        # RFC 7231 requires HTTP-dates to be in GMT; missing tzinfo is a
        # spec violation but treating it as UTC is the documented
        # ``parsedate_to_datetime`` fallback and matches what every other
        # HTTP client does in practice.
        target_datetime = target_datetime.replace(tzinfo=UTC)

    seconds_until_target: float = (target_datetime - clock.now_utc()).total_seconds()
    return max(seconds_until_target, 0.0)
