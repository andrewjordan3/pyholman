# tests/_transport/test_retry.py
"""Tests for pyholman._transport.retry."""

import time
from collections.abc import Callable

import pytest

from pyholman._config import RetryConfig
from pyholman._transport import (
    HolmanError,
    RateLimitError,
    TransientHolmanError,
)
from pyholman._transport.retry import _exponential_backoff_seconds, with_retry

__all__: list[str] = []

# Mirrors the private rate-limit buffer in retry.py. Duplicated here rather
# than imported because the production constant is underscore-prefixed and
# exporting it would leak an implementation detail. If the constant drifts
# in retry.py, these tests fail with a clear diff — exactly what we want.
_RATE_LIMIT_BUFFER_SECONDS: float = 0.5

# Default retry budget set by ``RetryConfig`` defaults. Mirrored here so
# assertions on call count read as "expected attempts" rather than a bare
# integer, and to satisfy ruff's PLR2004.
_DEFAULT_MAX_ATTEMPTS: int = 5
_DEFAULT_WAITS_BETWEEN: int = _DEFAULT_MAX_ATTEMPTS - 1

# Values used by tests that override the retry budget.
_OVERRIDE_MAX_ATTEMPTS: int = 3
_OVERRIDE_WAITS_BETWEEN: int = _OVERRIDE_MAX_ATTEMPTS - 1

# Default cap on exponential backoff from ``RetryConfig`` defaults.
_DEFAULT_BACKOFF_MAX_SECONDS: float = 60.0

# Marker value returned by the flaky-then-succeeds test.
_FLAKY_SUCCESS_ATTEMPTS: int = 2
_TRIVIAL_RETURN_VALUE: int = 42


def _default_retry_config() -> RetryConfig:
    """Return a retry config matching the library's documented defaults."""
    return RetryConfig()


# =============================================================================
# Pure backoff helper
# =============================================================================


class TestExponentialBackoffSeconds:
    @pytest.mark.parametrize(
        ('attempt_number', 'max_seconds', 'expected_wait'),
        [
            (1, 60.0, 1.0),
            (2, 60.0, 2.0),
            (3, 60.0, 4.0),
            (4, 60.0, 8.0),
            (5, 60.0, 16.0),
            (6, 60.0, 32.0),
            (7, 60.0, 60.0),
            (10, 60.0, 60.0),
            (5, 10.0, 10.0),
            (1, 0.5, 0.5),
        ],
    )
    def test_exponential_sequence_with_cap(
        self,
        attempt_number: int,
        max_seconds: float,
        expected_wait: float,
    ) -> None:
        assert (
            _exponential_backoff_seconds(
                attempt_number=attempt_number,
                max_seconds=max_seconds,
            )
            == expected_wait
        )


# =============================================================================
# with_retry behavior
# =============================================================================


@pytest.fixture
def recorded_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> list[float]:
    """
    Replace ``time.sleep`` with a recorder so retry tests run instantly.

    Tenacity's default sleep strategy calls ``time.sleep``; replacing it at
    the module level captures every wait the retry wrapper performs
    without blocking the test process. Returns the shared list of
    recorded durations so tests can assert on the sequence.
    """
    captured_durations: list[float] = []

    def _recording_sleep(seconds: float) -> None:
        captured_durations.append(seconds)

    monkeypatch.setattr(time, 'sleep', _recording_sleep)
    return captured_durations


class TestWithRetryRetries:
    def test_transient_error_retried_to_configured_limit(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0

        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise TransientHolmanError('still down')

        wrapped: Callable[[], None] = with_retry(_default_retry_config(), always_fails)
        with pytest.raises(TransientHolmanError, match='still down'):
            wrapped()

        # Default policy is 5 total attempts; 4 waits in between.
        assert call_count == _DEFAULT_MAX_ATTEMPTS
        assert len(recorded_sleeps) == _DEFAULT_WAITS_BETWEEN

    def test_rate_limit_error_retried_as_transient_subclass(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0

        def always_rate_limited() -> None:
            nonlocal call_count
            call_count += 1
            raise RateLimitError(retry_after_seconds=0.1)

        wrapped: Callable[[], None] = with_retry(
            _default_retry_config(), always_rate_limited
        )
        with pytest.raises(RateLimitError):
            wrapped()

        assert call_count == _DEFAULT_MAX_ATTEMPTS
        # Each wait is retry_after (0.1) + buffer (0.5) = 0.6s.
        assert recorded_sleeps == [pytest.approx(0.6)] * _DEFAULT_WAITS_BETWEEN

    def test_rate_limit_with_zero_retry_after_falls_through_to_backoff(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        # ``retry_after_seconds == 0.0`` signals "no server guidance"; the
        # wrapper must fall through to exponential backoff rather than
        # using the buffer alone.
        call_count: int = 0

        def rate_limited_without_hint() -> None:
            nonlocal call_count
            call_count += 1
            raise RateLimitError(retry_after_seconds=0.0)

        wrapped: Callable[[], None] = with_retry(
            _default_retry_config(), rate_limited_without_hint
        )
        with pytest.raises(RateLimitError):
            wrapped()

        assert call_count == _DEFAULT_MAX_ATTEMPTS
        assert recorded_sleeps == [1.0, 2.0, 4.0, 8.0]

    def test_transient_then_success_returns_value_without_extra_retries(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0

        def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TransientHolmanError('first flake')
            return 'ok'

        wrapped: Callable[[], str] = with_retry(_default_retry_config(), flaky)
        assert wrapped() == 'ok'
        assert call_count == _FLAKY_SUCCESS_ATTEMPTS
        # Exactly one wait between the two attempts.
        assert recorded_sleeps == [1.0]


class TestWithRetryNonRetryable:
    def test_plain_holman_error_propagates_without_retry(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0

        def fails_with_holman_error() -> None:
            nonlocal call_count
            call_count += 1
            raise HolmanError('permanent', status_code=403)

        wrapped: Callable[[], None] = with_retry(
            _default_retry_config(), fails_with_holman_error
        )
        with pytest.raises(HolmanError):
            wrapped()

        assert call_count == 1
        assert recorded_sleeps == []

    def test_unrelated_exception_propagates_without_retry(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0

        def fails_with_value_error() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError('bug in caller')

        wrapped: Callable[[], None] = with_retry(
            _default_retry_config(), fails_with_value_error
        )
        with pytest.raises(ValueError, match='bug in caller'):
            wrapped()

        assert call_count == 1
        assert recorded_sleeps == []


class TestWithRetryConfigOverrides:
    def test_max_attempts_override_limits_total_calls(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0
        override_config: RetryConfig = RetryConfig(max_attempts=_OVERRIDE_MAX_ATTEMPTS)

        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise TransientHolmanError('down')

        wrapped: Callable[[], None] = with_retry(override_config, always_fails)
        with pytest.raises(TransientHolmanError):
            wrapped()

        assert call_count == _OVERRIDE_MAX_ATTEMPTS
        assert len(recorded_sleeps) == _OVERRIDE_WAITS_BETWEEN

    def test_exhausted_retries_produce_expected_backoff_sequence(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        # Five total attempts → four waits at 1, 2, 4, 8 seconds (below cap).
        def always_fails() -> None:
            raise TransientHolmanError('down')

        wrapped: Callable[[], None] = with_retry(_default_retry_config(), always_fails)
        with pytest.raises(TransientHolmanError):
            wrapped()

        assert recorded_sleeps == [1.0, 2.0, 4.0, 8.0]

    def test_backoff_max_seconds_override_caps_waits(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        # With a 3-second cap, the unclamped sequence 1, 2, 4, 8 becomes
        # 1, 2, 3, 3.
        override_config: RetryConfig = RetryConfig(backoff_max_seconds=3.0)

        def always_fails() -> None:
            raise TransientHolmanError('down')

        wrapped: Callable[[], None] = with_retry(override_config, always_fails)
        with pytest.raises(TransientHolmanError):
            wrapped()

        assert recorded_sleeps == [1.0, 2.0, 3.0, 3.0]

    def test_max_attempts_one_disables_retries(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        call_count: int = 0
        override_config: RetryConfig = RetryConfig(max_attempts=1)

        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise TransientHolmanError('down')

        wrapped: Callable[[], None] = with_retry(override_config, always_fails)
        with pytest.raises(TransientHolmanError):
            wrapped()

        assert call_count == 1
        assert recorded_sleeps == []

    def test_default_config_default_backoff_cap_is_respected(
        self,
        recorded_sleeps: list[float],
    ) -> None:
        # Sanity check on the RetryConfig default: with attempts=10 and
        # the default 60s cap, the unclamped sequence 1, 2, 4, ..., 256
        # collapses to 1, 2, 4, 8, 16, 32, 60, 60, 60.
        override_config: RetryConfig = RetryConfig(max_attempts=10)

        def always_fails() -> None:
            raise TransientHolmanError('down')

        wrapped: Callable[[], None] = with_retry(override_config, always_fails)
        with pytest.raises(TransientHolmanError):
            wrapped()

        assert recorded_sleeps == [
            1.0,
            2.0,
            4.0,
            8.0,
            16.0,
            32.0,
            _DEFAULT_BACKOFF_MAX_SECONDS,
            _DEFAULT_BACKOFF_MAX_SECONDS,
            _DEFAULT_BACKOFF_MAX_SECONDS,
        ]


class TestWithRetryReturnType:
    def test_wrapped_function_forwards_arguments_and_return(self) -> None:
        # The wrapper should be an ordinary callable that forwards args
        # and return values unchanged on the success path.
        def add(left: int, right: int) -> int:
            return left + right

        wrapped: Callable[..., int] = with_retry(_default_retry_config(), add)
        assert wrapped(_TRIVIAL_RETURN_VALUE, 1) == _TRIVIAL_RETURN_VALUE + 1
