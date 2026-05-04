# tests/_transport/test_status.py
"""Tests for ``raise_for_holman_status`` and ``translate_httpx_request_error``."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from pyholman._clock import FrozenClock, SystemClock
from pyholman._transport import (
    HolmanError,
    RateLimitError,
    TransientHolmanError,
    raise_for_holman_status,
    translate_httpx_request_error,
)

__all__: list[str] = []


_FROZEN_NOW: datetime = datetime(2026, 1, 23, 12, 0, 0, tzinfo=UTC)


def _build_response(
    status_code: int,
    headers: dict[str, str] | None = None,
    text: str = '',
) -> httpx.Response:
    """Construct a stand-alone ``httpx.Response`` for assertions."""
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        content=text.encode('utf-8'),
    )


# =============================================================================
# raise_for_holman_status — success
# =============================================================================


class TestSuccessStatus:
    @pytest.mark.parametrize('status_code', [200, 201, 202, 204, 299])
    def test_2xx_returns_none(self, status_code: int) -> None:
        response: httpx.Response = _build_response(status_code, text='ok')
        assert raise_for_holman_status(response, clock=SystemClock()) is None


# =============================================================================
# raise_for_holman_status — 429
# =============================================================================


class TestRateLimitStatus:
    def test_429_with_integer_retry_after(self) -> None:
        response: httpx.Response = _build_response(
            429, headers={'Retry-After': '42'}, text='slow down'
        )
        with pytest.raises(RateLimitError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        assert excinfo.value.retry_after_seconds == 42.0
        assert excinfo.value.response_body == 'slow down'
        assert excinfo.value.status_code == 429

    def test_429_with_http_date_retry_after(self) -> None:
        future_offset_seconds: int = 30
        future_target: datetime = _FROZEN_NOW + timedelta(seconds=future_offset_seconds)
        http_date: str = format_datetime(future_target, usegmt=True)
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_NOW)

        response: httpx.Response = _build_response(
            429, headers={'Retry-After': http_date}, text='slow down'
        )
        with pytest.raises(RateLimitError) as excinfo:
            raise_for_holman_status(response, clock=clock)

        # Frozen clock + IMF-fixdate gives exact second-level equality.
        assert excinfo.value.retry_after_seconds == float(future_offset_seconds)

    def test_429_without_retry_after_header_yields_zero(self) -> None:
        response: httpx.Response = _build_response(429, text='slow down')
        with pytest.raises(RateLimitError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        assert excinfo.value.retry_after_seconds == 0.0


# =============================================================================
# raise_for_holman_status — 4xx (non-429)
# =============================================================================


class TestClientErrorStatus:
    @pytest.mark.parametrize('status_code', [400, 401, 403, 404, 422])
    def test_4xx_raises_holman_error(self, status_code: int) -> None:
        response: httpx.Response = _build_response(status_code, text='nope')
        with pytest.raises(HolmanError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        # ``HolmanError`` has the rate-limit and transient subclasses, so
        # check the *exact* type to confirm dispatch landed in the right
        # arm.
        assert type(excinfo.value) is HolmanError
        assert excinfo.value.status_code == status_code
        assert excinfo.value.response_body == 'nope'


# =============================================================================
# raise_for_holman_status — 5xx
# =============================================================================


class TestServerErrorStatus:
    @pytest.mark.parametrize('status_code', [500, 502, 503, 504])
    def test_5xx_raises_transient_holman_error(self, status_code: int) -> None:
        response: httpx.Response = _build_response(status_code, text='boom')
        with pytest.raises(TransientHolmanError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        # Distinguish from ``RateLimitError``, which is also transient.
        assert type(excinfo.value) is TransientHolmanError
        assert excinfo.value.status_code == status_code
        assert excinfo.value.response_body == 'boom'


# =============================================================================
# raise_for_holman_status — unexpected (1xx, 3xx)
# =============================================================================


class TestUnexpectedStatus:
    @pytest.mark.parametrize('status_code', [100, 101, 199])
    def test_1xx_raises_holman_error(self, status_code: int) -> None:
        response: httpx.Response = _build_response(status_code)
        with pytest.raises(HolmanError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        assert type(excinfo.value) is HolmanError
        assert excinfo.value.status_code == status_code
        assert 'informational' in str(excinfo.value).lower()

    @pytest.mark.parametrize('status_code', [301, 302, 304, 307])
    def test_3xx_raises_holman_error(self, status_code: int) -> None:
        response: httpx.Response = _build_response(status_code)
        with pytest.raises(HolmanError) as excinfo:
            raise_for_holman_status(response, clock=SystemClock())

        assert type(excinfo.value) is HolmanError
        assert excinfo.value.status_code == status_code
        assert 'redirect' in str(excinfo.value).lower()


# =============================================================================
# translate_httpx_request_error
# =============================================================================


class TestTranslateHttpxRequestError:
    def test_timeout_yields_transient_with_timeout_prefix(self) -> None:
        timeout_error: httpx.TimeoutException = httpx.ReadTimeout('read timed out')

        translated: TransientHolmanError = translate_httpx_request_error(timeout_error)

        assert isinstance(translated, TransientHolmanError)
        assert str(translated).startswith('Request timeout:')
        assert 'read timed out' in str(translated)

    def test_connect_error_yields_transient_with_connection_prefix(self) -> None:
        connect_error: httpx.ConnectError = httpx.ConnectError('refused')

        translated: TransientHolmanError = translate_httpx_request_error(connect_error)

        assert isinstance(translated, TransientHolmanError)
        assert str(translated).startswith('Connection failed:')

    def test_other_network_error_yields_transient_with_network_prefix(
        self,
    ) -> None:
        # ``ReadError`` is a ``NetworkError`` that is not a ``ConnectError``,
        # so it exercises the third branch of the dispatch.
        read_error: httpx.ReadError = httpx.ReadError('peer reset')

        translated: TransientHolmanError = translate_httpx_request_error(read_error)

        assert isinstance(translated, TransientHolmanError)
        assert str(translated).startswith('Network error:')

    def test_other_request_error_yields_transient_with_generic_prefix(
        self,
    ) -> None:
        # ``DecodingError`` is a ``RequestError`` that is neither a timeout
        # nor a network error — the catch-all branch handles it.
        request: httpx.Request = httpx.Request('GET', 'https://example.test/')
        decoding_error: httpx.DecodingError = httpx.DecodingError(
            'bad encoding', request=request
        )

        translated: TransientHolmanError = translate_httpx_request_error(decoding_error)

        assert isinstance(translated, TransientHolmanError)
        assert str(translated).startswith('HTTP request failed:')
