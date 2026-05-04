# tests/_transport/test_exceptions.py
"""Tests for the transport exception hierarchy."""

import pytest

from pyholman._transport import HolmanError, RateLimitError, TransientHolmanError

__all__: list[str] = []

# The truncation threshold baked into exceptions.py. Mirrored here (not
# imported — it is module-private) so these tests double as an early-warning
# signal if the production constant drifts.
_RESPONSE_BODY_TRUNCATION_LENGTH: int = 200

# Rate-limit responses always carry HTTP 429. Pulled out for readability
# and to satisfy ruff's PLR2004 (no bare magic numbers in comparisons).
_HTTP_429: int = 429
_HTTP_400: int = 400
_HTTP_500: int = 500
_HTTP_504: int = 504


# =============================================================================
# HolmanError
# =============================================================================


class TestHolmanErrorConstruction:
    def test_message_only_sets_none_for_other_fields(self) -> None:
        error: HolmanError = HolmanError('something broke')
        assert str(error) == 'something broke'
        assert error.status_code is None
        assert error.response_body is None

    def test_with_status_code(self) -> None:
        error: HolmanError = HolmanError('bad request', status_code=_HTTP_400)
        assert error.status_code == _HTTP_400
        assert error.response_body is None

    def test_with_response_body(self) -> None:
        error: HolmanError = HolmanError(
            'bad response', response_body='{"detail": "nope"}'
        )
        assert error.response_body == '{"detail": "nope"}'
        assert error.status_code is None

    def test_with_all_three_fields(self) -> None:
        error: HolmanError = HolmanError(
            'bad request',
            status_code=_HTTP_400,
            response_body='boom',
        )
        assert str(error) == 'bad request'
        assert error.status_code == _HTTP_400
        assert error.response_body == 'boom'


class TestHolmanErrorCatchable:
    def test_catchable_as_exception(self) -> None:
        # ``Exception`` is intentional here — we're confirming the class
        # is a plain subclass of the stdlib base; ``match=`` satisfies PT011.
        with pytest.raises(Exception, match='kaboom'):
            raise HolmanError('kaboom')

    def test_catchable_as_holman_error(self) -> None:
        with pytest.raises(HolmanError):
            raise HolmanError('kaboom')


class TestHolmanErrorRepr:
    def test_repr_with_all_fields(self) -> None:
        error: HolmanError = HolmanError(
            'boom', status_code=_HTTP_500, response_body='server down'
        )
        rendered: str = repr(error)
        assert rendered == (
            "HolmanError(message='boom', status_code=500, response_body='server down')"
        )

    def test_repr_renders_none_for_missing_fields(self) -> None:
        error: HolmanError = HolmanError('boom')
        assert repr(error) == (
            "HolmanError(message='boom', status_code=None, response_body=None)"
        )

    def test_repr_response_body_exactly_at_boundary_not_truncated(self) -> None:
        body_at_boundary: str = 'a' * _RESPONSE_BODY_TRUNCATION_LENGTH
        error: HolmanError = HolmanError('boom', response_body=body_at_boundary)
        rendered: str = repr(error)
        # No truncation marker — the body should appear verbatim in quotes.
        assert f"response_body='{body_at_boundary}'" in rendered
        assert 'chars)' not in rendered

    def test_repr_response_body_just_over_boundary_is_truncated(self) -> None:
        body_over_boundary: str = 'b' * (_RESPONSE_BODY_TRUNCATION_LENGTH + 1)
        error: HolmanError = HolmanError('boom', response_body=body_over_boundary)
        rendered: str = repr(error)
        expected_prefix: str = 'b' * _RESPONSE_BODY_TRUNCATION_LENGTH
        assert (
            f"response_body='{expected_prefix}...' ({len(body_over_boundary)} chars)"
        ) in rendered

    def test_repr_response_body_long_input_truncated(self) -> None:
        body_long: str = 'c' * 10_000
        error: HolmanError = HolmanError('boom', response_body=body_long)
        rendered: str = repr(error)
        expected_prefix: str = 'c' * _RESPONSE_BODY_TRUNCATION_LENGTH
        assert (f"response_body='{expected_prefix}...' (10000 chars)") in rendered


# =============================================================================
# TransientHolmanError
# =============================================================================


class TestTransientHolmanError:
    def test_is_subclass_of_holman_error(self) -> None:
        assert issubclass(TransientHolmanError, HolmanError)

    def test_inherits_repr_unchanged(self) -> None:
        # ``__repr__`` is not overridden on TransientHolmanError; only the
        # class name should differ from the HolmanError version.
        transient: TransientHolmanError = TransientHolmanError(
            'gateway timeout', status_code=_HTTP_504, response_body='x' * 5
        )
        assert repr(transient) == (
            "TransientHolmanError(message='gateway timeout', "
            "status_code=504, response_body='xxxxx')"
        )

    def test_catchable_as_holman_error(self) -> None:
        with pytest.raises(HolmanError):
            raise TransientHolmanError('retry me')


# =============================================================================
# RateLimitError
# =============================================================================


class TestRateLimitErrorHierarchy:
    def test_is_subclass_of_transient(self) -> None:
        assert issubclass(RateLimitError, TransientHolmanError)

    def test_is_subclass_of_holman_error(self) -> None:
        assert issubclass(RateLimitError, HolmanError)


class TestRateLimitErrorConstruction:
    def test_retry_after_only_has_status_code_429_and_no_body(self) -> None:
        retry_after: float = 12.0
        error: RateLimitError = RateLimitError(retry_after_seconds=retry_after)
        assert error.retry_after_seconds == retry_after
        assert error.status_code == _HTTP_429
        assert error.response_body is None

    def test_with_response_body(self) -> None:
        error: RateLimitError = RateLimitError(
            retry_after_seconds=5.0,
            response_body='slow down',
        )
        assert error.response_body == 'slow down'
        assert error.status_code == _HTTP_429

    def test_status_code_always_429(self) -> None:
        # Construct several instances with wildly different wait values to
        # confirm status_code is hard-wired to 429, not derived from input.
        for wait in (0.0, 0.1, 1.0, 999.0):
            assert RateLimitError(retry_after_seconds=wait).status_code == _HTTP_429

    @pytest.mark.parametrize('retry_after', [0.0, 0.25, 1.5, 10.0, 123.4])
    def test_retry_after_stored_verbatim(self, retry_after: float) -> None:
        error: RateLimitError = RateLimitError(retry_after_seconds=retry_after)
        assert error.retry_after_seconds == retry_after

    def test_message_contains_retry_after(self) -> None:
        # The message is derived from retry_after_seconds in the constructor;
        # it must surface that value for users who read ``str(error)``.
        error: RateLimitError = RateLimitError(retry_after_seconds=7.5)
        assert '7.5' in str(error)


class TestRateLimitErrorRepr:
    def test_repr_includes_retry_after_and_omits_message(self) -> None:
        error: RateLimitError = RateLimitError(
            retry_after_seconds=3.0,
            response_body='too fast',
        )
        rendered: str = repr(error)
        assert rendered == (
            'RateLimitError(retry_after_seconds=3.0, status_code=429, '
            "response_body='too fast')"
        )
        # The base-class ``message='...'`` prefix is intentionally omitted
        # from the RateLimitError repr — the retry-after value carries the
        # same information.
        assert 'message=' not in rendered

    def test_repr_renders_none_for_absent_body(self) -> None:
        error: RateLimitError = RateLimitError(retry_after_seconds=0.0)
        assert repr(error) == (
            'RateLimitError(retry_after_seconds=0.0, status_code=429, '
            'response_body=None)'
        )

    def test_repr_truncates_large_body(self) -> None:
        body: str = 'z' * 500
        error: RateLimitError = RateLimitError(
            retry_after_seconds=1.0,
            response_body=body,
        )
        rendered: str = repr(error)
        expected_prefix: str = 'z' * _RESPONSE_BODY_TRUNCATION_LENGTH
        assert f"response_body='{expected_prefix}...' (500 chars)" in rendered
