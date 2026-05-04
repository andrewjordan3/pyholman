# src/pyholman/_transport/retry.py
"""
Retry policy for pyholman HTTP requests.

Exposes a single entry point: :func:`with_retry`. Given a
``RetryConfig`` and a callable, it returns a wrapped callable that
retries the original on ``TransientHolmanError`` (and its subclass
``RateLimitError``) per the configured policy.

Policy:

    - Retry on ``TransientHolmanError`` only. Non-retryable errors
      (``HolmanError`` with 4xx != 429) propagate immediately.

    - Rate-limit-aware wait: when the exception is a ``RateLimitError``
      with a positive ``retry_after_seconds``, wait that long plus a
      small buffer (to avoid retrying just as the window reopens).
      Otherwise fall back to exponential backoff capped at
      ``config.backoff_max_seconds``.

    - Stop condition: ``config.max_attempts`` total attempts.
      Conservative enough to weather most Zscaler hiccups and short
      Holman outages without masking real failures for long.

Tuning constants:

    - ``_BACKOFF_MULTIPLIER = 1.0``: produces the sequence
      1s, 2s, 4s, 8s, ... clamped to ``backoff_max_seconds``.

    - ``_RATE_LIMIT_BUFFER_SECONDS = 0.5``: a half-second pad after the
      server's Retry-After window. Avoids racing the window boundary.

:func:`with_retry` is an internal helper of the transport layer; only
:func:`pyholman._transport.request.send_request` calls it. It is not
part of the package's public surface — callers go through
``send_request`` instead and get retry for free.
"""

import logging
from collections.abc import Callable
from typing import Final

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
)

from pyholman._config import RetryConfig
from pyholman._transport.exceptions import RateLimitError, TransientHolmanError

__all__: list[str] = ['with_retry']

logger: logging.Logger = logging.getLogger(__name__)


# =============================================================================
# Tuning constants
# =============================================================================
# Module-private: internal tuning, not user config. The user-configurable
# knobs (max_attempts, backoff_max_seconds) live on ``RetryConfig``.
# =============================================================================

# Base multiplier for exponential backoff: wait = multiplier * 2^(attempt - 1).
_BACKOFF_MULTIPLIER: Final[float] = 1.0

# Extra padding added to a server-supplied Retry-After wait, so we don't
# retry at the exact instant the rate-limit window reopens.
_RATE_LIMIT_BUFFER_SECONDS: Final[float] = 0.5


# =============================================================================
# Wait strategy
# =============================================================================


def _exponential_backoff_seconds(attempt_number: int, max_seconds: float) -> float:
    """
    Compute the exponential backoff wait for a given attempt number.

    Produces the sequence (for MULTIPLIER=1.0, max_seconds=60):
    1s, 2s, 4s, 8s, 16s, 32s, 60s, 60s, ...

    Args:
        attempt_number: 1-based attempt count. The first retry is attempt 2;
            tenacity's ``RetryCallState.attempt_number`` matches this
            convention.
        max_seconds: Upper bound for the returned wait. Comes from
            ``RetryConfig.backoff_max_seconds``.

    Returns:
        Wait duration in seconds, capped at ``max_seconds``.
    """
    exponential_wait: float = _BACKOFF_MULTIPLIER * (2 ** (attempt_number - 1))
    return min(exponential_wait, max_seconds)


# =============================================================================
# Retry application
# =============================================================================


def with_retry[T](
    retry_config: RetryConfig,
    func: Callable[..., T],
) -> Callable[..., T]:
    """
    Return ``func`` wrapped in pyholman's retry policy.

    The wrapped callable re-invokes ``func`` on every
    ``TransientHolmanError`` (or ``RateLimitError``) up to
    ``retry_config.max_attempts`` total attempts, waiting between
    attempts according to the rate-limit-aware / exponential-backoff
    policy documented at the module level. Non-retryable errors
    (``HolmanError`` with 4xx != 429, ``ValueError``, …) propagate
    immediately.

    Unlike a decorator, this helper takes the function as an argument.
    That lets the internal caller
    (:func:`pyholman._transport.request.send_request`) construct a
    closure once per outer invocation and wrap it in one line, without
    having to expose an intermediate ``@decorator`` object.

    Type parameters:
        T: Return type of ``func``. Preserved on the wrapped callable so
            the caller does not lose type information.

    Args:
        retry_config: Policy controlling total attempt count and the
            upper bound on exponential backoff between retries.
        func: The callable to wrap. Any positional or keyword arguments
            accepted at call time are forwarded unchanged.

    Returns:
        A callable with the same signature as ``func``. Raises the
        final exception on exhaustion.
    """
    backoff_max_seconds: float = retry_config.backoff_max_seconds

    def _wait_for_rate_limit_or_backoff(retry_state: RetryCallState) -> float:
        """
        Tenacity wait strategy that prefers server-supplied Retry-After
        over exponential backoff.

        Captures ``backoff_max_seconds`` from the enclosing
        :func:`with_retry` call so tenacity's fixed
        ``(RetryCallState) -> float`` callback signature is honored
        without passing the cap through global state.
        """
        exception: BaseException | None = (
            retry_state.outcome.exception() if retry_state.outcome else None
        )

        if isinstance(exception, RateLimitError) and exception.retry_after_seconds > 0:
            wait_seconds: float = (
                exception.retry_after_seconds + _RATE_LIMIT_BUFFER_SECONDS
            )
            logger.debug(
                'Rate-limit wait: using server Retry-After of %.1fs (+%.1fs buffer)',
                exception.retry_after_seconds,
                _RATE_LIMIT_BUFFER_SECONDS,
            )
            return wait_seconds

        backoff_seconds: float = _exponential_backoff_seconds(
            attempt_number=retry_state.attempt_number,
            max_seconds=backoff_max_seconds,
        )
        logger.debug(
            'Exponential backoff wait: attempt %d -> %.1fs',
            retry_state.attempt_number,
            backoff_seconds,
        )
        return backoff_seconds

    tenacity_decorator = retry(
        retry=retry_if_exception_type(TransientHolmanError),
        wait=_wait_for_rate_limit_or_backoff,
        stop=stop_after_attempt(retry_config.max_attempts),
        reraise=True,
    )
    wrapped: Callable[..., T] = tenacity_decorator(func)
    return wrapped
