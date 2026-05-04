# src/pyholman/_transport/status.py
"""
Translate ``httpx`` outcomes into the pyholman exception hierarchy.

Two halves of the same boundary:

    - :func:`raise_for_holman_status` — given an ``httpx.Response`` that
      came back from the server, decide whether it is a success or one
      of the documented failure classes (rate limit, client error,
      transient server error, unexpected status), and raise the
      appropriate pyholman exception in the failure cases.

    - :func:`translate_httpx_request_error` — given a connection-level
      ``httpx.RequestError`` (timeout, DNS failure, TLS error,
      connection reset), construct (but do not raise) a
      :class:`TransientHolmanError` so the caller can ``raise ... from``
      the original error and preserve the cause chain.

The split exists because the two failure modes happen at different
points in the request lifecycle: ``RequestError`` fires before any
response is received, while ``raise_for_holman_status`` always operates
on a response. Keeping the two functions distinct keeps each one's
inputs and outputs unambiguous and lets the composition helper
(``send_request`` in ``request.py``) pair them in the obvious order.
"""

import logging
from http import HTTPStatus
from typing import Final

import httpx

from pyholman._clock import Clock
from pyholman._transport.exceptions import (
    HolmanError,
    RateLimitError,
    TransientHolmanError,
)
from pyholman._transport.retry_after import parse_retry_after_header

__all__: list[str] = [
    'raise_for_holman_status',
    'translate_httpx_request_error',
]

logger: logging.Logger = logging.getLogger(__name__)


# =============================================================================
# HTTP status-class boundaries
# =============================================================================
# Named so the ``match`` arms read as status-class membership rather than
# a wall of magic numbers, and so ruff's PLR2004 stays clean. The values
# are the standard inclusive-lower / exclusive-upper bounds for each
# class as defined by RFC 9110 §15.
# =============================================================================

_HTTP_INFORMATIONAL_MIN: Final[int] = 100
_HTTP_SUCCESS_MIN: Final[int] = 200
_HTTP_REDIRECT_MIN: Final[int] = 300
_HTTP_CLIENT_ERROR_MIN: Final[int] = 400
_HTTP_SERVER_ERROR_MIN: Final[int] = 500
_HTTP_SERVER_ERROR_MAX_EXCLUSIVE: Final[int] = 600
# 429 is matched as ``HTTPStatus.TOO_MANY_REQUESTS`` in the ``case`` arm
# below — bare integer-valued names confuse ``match`` (it would treat
# them as capture patterns), but a dotted reference like
# ``HTTPStatus.TOO_MANY_REQUESTS`` is unambiguously a value pattern.


def raise_for_holman_status(response: httpx.Response, *, clock: Clock) -> None:
    """
    Raise the appropriate pyholman exception for a non-2xx response.

    Dispatch follows the documented HTTP status classes:

        - ``2xx`` — success; return without raising.
        - ``429`` — :class:`RateLimitError`, with ``retry_after_seconds``
          parsed from the ``Retry-After`` header (``0.0`` when absent).
        - ``4xx`` (excluding 429) — :class:`HolmanError`. Non-retryable
          client error; the retry decorator does not catch this type.
        - ``5xx`` — :class:`TransientHolmanError`. Retryable server error.
        - ``1xx`` / ``3xx`` — :class:`HolmanError`. Holman's REST API
          shouldn't send informational or redirect responses, and
          pyholman doesn't follow redirects; treating these as errors
          surfaces the surprise rather than hiding it.

    The exception's ``response_body`` carries the full response text so
    callers can inspect the payload for diagnostics. The message is kept
    short — it names the status and a brief description, not the body.

    Args:
        response: The HTTP response returned by ``httpx``. Already
            received in full; this function does not stream.
        clock: Time provider threaded through to
            :func:`parse_retry_after_header` for the HTTP-date branch
            of ``Retry-After`` parsing. Required keyword-only so the
            429 path is deterministically testable; harmless on every
            other status because it is only consulted by the 429 arm.

    Returns:
        ``None`` for any 2xx response.

    Raises:
        RateLimitError: When ``response.status_code == 429``.
        TransientHolmanError: For any 5xx response.
        HolmanError: For 4xx (excluding 429), 1xx, or 3xx responses.
    """
    status_code: int = response.status_code

    match status_code:
        case status if _HTTP_SUCCESS_MIN <= status < _HTTP_REDIRECT_MIN:
            return
        case HTTPStatus.TOO_MANY_REQUESTS:
            retry_after_seconds: float = parse_retry_after_header(
                response.headers.get('Retry-After'),
                clock=clock,
            )
            raise RateLimitError(
                retry_after_seconds=retry_after_seconds,
                response_body=response.text,
            )
        case status if _HTTP_CLIENT_ERROR_MIN <= status < _HTTP_SERVER_ERROR_MIN:
            raise HolmanError(
                message=f'Client error: HTTP {status}',
                status_code=status,
                response_body=response.text,
            )
        case status if (
            _HTTP_SERVER_ERROR_MIN <= status < _HTTP_SERVER_ERROR_MAX_EXCLUSIVE
        ):
            raise TransientHolmanError(
                message=f'Server error: HTTP {status}',
                status_code=status,
                response_body=response.text,
            )
        case status if _HTTP_INFORMATIONAL_MIN <= status < _HTTP_SUCCESS_MIN:
            raise HolmanError(
                message=f'Unexpected informational response: HTTP {status}',
                status_code=status,
                response_body=response.text,
            )
        case status if _HTTP_REDIRECT_MIN <= status < _HTTP_CLIENT_ERROR_MIN:
            raise HolmanError(
                message=f'Unexpected redirect response: HTTP {status}',
                status_code=status,
                response_body=response.text,
            )
        case status:
            # Status outside the standard 100..599 range. Unreachable in
            # practice (httpx would reject it), but the match statement
            # needs an exhaustive arm and a loud failure here is
            # preferable to silently treating a malformed status as a
            # success.
            raise HolmanError(
                message=f'Unexpected status code outside HTTP range: {status}',
                status_code=status,
                response_body=response.text,
            )


def translate_httpx_request_error(
    error: httpx.RequestError,
) -> TransientHolmanError:
    """
    Build a :class:`TransientHolmanError` from a connection-level
    ``httpx.RequestError``.

    All ``RequestError`` subclasses represent failures that happened
    before a response was received — timeouts, DNS failures, TLS
    handshake errors, connection resets — and all of them are retryable
    in pyholman's policy. The retry decorator catches
    ``TransientHolmanError``; returning that type here is what makes
    the request retry on the next attempt.

    Dispatch picks a category-specific message prefix so log output and
    exception reprs identify the failure mode at a glance:

        - :class:`httpx.TimeoutException` → ``'Request timeout: ...'``.
        - :class:`httpx.ConnectError` → ``'Connection failed: ...'``.
        - :class:`httpx.NetworkError` (other) → ``'Network error: ...'``.
        - Any other :class:`httpx.RequestError` → ``'HTTP request failed: ...'``.

    The function returns the exception rather than raising it so the
    caller can chain the original via ``raise ... from error``,
    preserving the underlying ``httpx`` traceback as ``__cause__``.

    Args:
        error: The ``httpx.RequestError`` raised during request send.

    Returns:
        A :class:`TransientHolmanError` instance, ready to raise.
        ``status_code`` and ``response_body`` are ``None`` because the
        failure occurred before any response was received.
    """
    # Order matters: ``ConnectError`` is a subclass of ``NetworkError``,
    # so the more-specific check has to come first. ``TimeoutException``
    # is its own branch off ``TransportError`` and unrelated to the
    # network-error subtree.
    if isinstance(error, httpx.TimeoutException):
        message: str = f'Request timeout: {error}'
    elif isinstance(error, httpx.ConnectError):
        message = f'Connection failed: {error}'
    elif isinstance(error, httpx.NetworkError):
        message = f'Network error: {error}'
    else:
        message = f'HTTP request failed: {error}'

    return TransientHolmanError(message=message)
