# tests/_transport/test_request.py
"""Tests for the ``send_request`` helper and ``parse_response_body``."""

import time
from collections.abc import Callable

import httpx
import pytest

from pyholman._clock import SystemClock
from pyholman._config import RetryConfig
from pyholman._core import FrozenModel, ResponseModel
from pyholman._transport import (
    HolmanError,
    HttpTransport,
    RateLimitError,
    TransientHolmanError,
    parse_response_body,
    send_request,
)

__all__: list[str] = []


# Retry is disabled for most tests: we want to observe the raw outcome
# of a single send without the retry wrapper muddying call counts.
_NO_RETRY: RetryConfig = RetryConfig(max_attempts=1)


def _build_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    retry_config: RetryConfig = _NO_RETRY,
) -> HttpTransport:
    """Build an ``HttpTransport`` whose client routes requests through ``handler``."""
    mock_transport: httpx.MockTransport = httpx.MockTransport(handler)
    client: httpx.Client = httpx.Client(transport=mock_transport)
    return HttpTransport(
        client=client,
        retry_config=retry_config,
        clock=SystemClock(),
    )


def _build_request() -> httpx.Request:
    return httpx.Request('GET', 'https://api.holman.solutions/v1/things')


@pytest.fixture
def silenced_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap ``time.sleep`` for a no-op so retry tests do not actually block."""

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(time, 'sleep', _no_sleep)


# =============================================================================
# Happy path
# =============================================================================


class TestSendRequestHappyPath:
    def test_2xx_returns_response_unchanged(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'{"ok": true}')

        transport: HttpTransport = _build_transport(_handler)
        try:
            response: httpx.Response = send_request(transport, _build_request())
        finally:
            transport.client.close()

        assert response.status_code == 200
        assert response.text == '{"ok": true}'


# =============================================================================
# Connection-level failures
# =============================================================================


class TestSendRequestRequestErrors:
    def test_request_error_chains_through_cause(self) -> None:
        original_error: httpx.ConnectError = httpx.ConnectError('refused')

        def _handler(request: httpx.Request) -> httpx.Response:
            raise original_error

        transport: HttpTransport = _build_transport(_handler)
        try:
            with pytest.raises(TransientHolmanError) as excinfo:
                send_request(transport, _build_request())
        finally:
            transport.client.close()

        # ``__cause__`` preserves the original httpx exception so the
        # traceback is not lost when the translated ``TransientHolmanError``
        # is caught further up.
        assert excinfo.value.__cause__ is original_error
        assert str(excinfo.value).startswith('Connection failed:')


# =============================================================================
# Response-level failures
# =============================================================================


class TestSendRequestResponseErrors:
    def test_4xx_non_429_raises_holman_error(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b'not found')

        transport: HttpTransport = _build_transport(_handler)
        try:
            with pytest.raises(HolmanError) as excinfo:
                send_request(transport, _build_request())
        finally:
            transport.client.close()

        assert type(excinfo.value) is HolmanError
        assert excinfo.value.status_code == 404
        assert excinfo.value.response_body == 'not found'

    def test_429_raises_rate_limit_error_with_parsed_retry_after(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429, headers={'Retry-After': '15'}, content=b'slow down'
            )

        transport: HttpTransport = _build_transport(_handler)
        try:
            with pytest.raises(RateLimitError) as excinfo:
                send_request(transport, _build_request())
        finally:
            transport.client.close()

        assert excinfo.value.retry_after_seconds == 15.0
        assert excinfo.value.response_body == 'slow down'

    def test_5xx_raises_transient_holman_error(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b'unavailable')

        transport: HttpTransport = _build_transport(_handler)
        try:
            with pytest.raises(TransientHolmanError) as excinfo:
                send_request(transport, _build_request())
        finally:
            transport.client.close()

        assert type(excinfo.value) is TransientHolmanError
        assert excinfo.value.status_code == 503
        assert excinfo.value.response_body == 'unavailable'


# =============================================================================
# Retry wired in via the transport
# =============================================================================


class TestSendRequestRetry:
    def test_transient_then_success_retries_and_returns(
        self, silenced_sleep: None
    ) -> None:
        del silenced_sleep  # fixture is applied, value unused
        call_count: int = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, content=b'first flake')
            return httpx.Response(200, content=b'ok')

        transport: HttpTransport = _build_transport(
            _handler, retry_config=RetryConfig(max_attempts=2)
        )
        try:
            response: httpx.Response = send_request(transport, _build_request())
        finally:
            transport.client.close()

        assert response.status_code == 200
        # Retry fired exactly once: the 500 caused a retry, the 200
        # succeeded on the second attempt.
        assert call_count == 2


# =============================================================================
# parse_response_body
# =============================================================================


class _SampleStrictModel(FrozenModel):
    """Strict model used for required-field and malformed-body tests."""

    label: str
    count: int


class _SampleTolerantModel(ResponseModel):
    """Tolerant model used for the ``extra='ignore'`` assertion."""

    label: str


def _response_with(
    body: bytes,
    *,
    status_code: int = 200,
) -> httpx.Response:
    """Construct a stand-alone ``httpx.Response`` with ``body``."""
    return httpx.Response(status_code=status_code, content=body)


class TestParseResponseBodyHappyPath:
    def test_valid_body_returns_parsed_model(self) -> None:
        response: httpx.Response = _response_with(b'{"label":"ok","count":3}')
        parsed: _SampleStrictModel = parse_response_body(
            response, _SampleStrictModel, 'the test endpoint'
        )
        assert parsed.label == 'ok'
        assert parsed.count == 3

    def test_extra_fields_ignored_by_tolerant_model(self) -> None:
        response: httpx.Response = _response_with(
            b'{"label":"ok","not_modeled_yet":"surplus"}'
        )
        parsed: _SampleTolerantModel = parse_response_body(
            response, _SampleTolerantModel, 'the test endpoint'
        )
        assert parsed.label == 'ok'
        assert not hasattr(parsed, 'not_modeled_yet')


class TestParseResponseBodyFailures:
    def test_invalid_json_raises_holman_error_chained(self) -> None:
        response: httpx.Response = _response_with(b'{"label":"ok"}', status_code=200)
        with pytest.raises(HolmanError) as excinfo:
            parse_response_body(response, _SampleStrictModel, '/vehicles/basic-query')

        # The original ``ValidationError`` must be preserved as the
        # cause so callers inspecting ``__cause__`` can tell shape
        # mismatches apart from network failures.
        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'
        # The caller-supplied endpoint description appears verbatim in
        # the error message — without it, log output couldn't identify
        # where the bad shape came from.
        assert '/vehicles/basic-query' in str(excinfo.value)
        # Diagnostic attributes carry the response details.
        assert excinfo.value.status_code == 200
        assert excinfo.value.response_body == '{"label":"ok"}'

    def test_empty_body_raises_holman_error(self) -> None:
        response: httpx.Response = _response_with(b'')
        with pytest.raises(HolmanError) as excinfo:
            parse_response_body(response, _SampleStrictModel, 'the test endpoint')
        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'
        assert excinfo.value.response_body == ''

    def test_non_json_body_raises_holman_error(self) -> None:
        response: httpx.Response = _response_with(b'<html>oops</html>')
        with pytest.raises(HolmanError) as excinfo:
            parse_response_body(response, _SampleStrictModel, 'the test endpoint')
        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'
