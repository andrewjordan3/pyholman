# tests/_auth/test_token_manager.py
"""Tests for :class:`TokenManager` — OAuth2 client-credentials lifecycle."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent
from urllib.parse import parse_qs

import httpx
import pytest

from pyholman._auth import TokenManager
from pyholman._clock import Clock, FrozenClock, SystemClock
from pyholman._config import RetryConfig, UserConfig
from pyholman._core.constants import PACKAGE_NAME
from pyholman._transport import HolmanError, HttpTransport

__all__: list[str] = []


# =============================================================================
# Shared helpers and fixtures
# =============================================================================


# Mirrors the private refresh skew in ``token_manager.py``. Duplicated
# here rather than imported because the production constant is private;
# drift in the production value surfaces as a test failure with a clear
# diff.
_REFRESH_SKEW_SECONDS: float = 30.0

# Values used to construct representative token responses. Declared at
# module scope so tests can refer back to the same numbers when
# asserting stored state.
_TEST_ACCESS_TOKEN: str = 'abc123-token'
_TEST_TOKEN_TYPE: str = 'Bearer'
_TEST_EXPIRES_IN: int = 3600
_TEST_SCOPE: str = 'read'
_TOKEN_ENDPOINT_PATH: str = '/sso/sts/connect/token'


def _token_payload(
    *,
    access_token: str = _TEST_ACCESS_TOKEN,
    token_type: str = _TEST_TOKEN_TYPE,
    expires_in: int = _TEST_EXPIRES_IN,
    scope: str = _TEST_SCOPE,
) -> bytes:
    """Build a JSON token-response body with the given overrides."""
    return (
        b'{'
        b'"access_token":"' + access_token.encode('utf-8') + b'",'
        b'"token_type":"' + token_type.encode('utf-8') + b'",'
        b'"expires_in":' + str(expires_in).encode('utf-8') + b','
        b'"scope":"' + scope.encode('utf-8') + b'"'
        b'}'
    )


_YAML_BODY_TEMPLATE: str = dedent(
    """\
    credentials:
      client_id: '{client_id}'
    api:
      base_url: '{base_url}'
    fleet:
      organization_id: 'ORG1'
      lessee_codes:
        - 'ABCD'
    working_directory: '{output_dir}'
    resources:
      - name: vehicles
    """
)


def _build_user_config(
    tmp_path: Path,
    *,
    base_url: str = 'https://api.holman.solutions',
    client_id: str = 'my-client-id',
) -> UserConfig:
    """Write a minimal YAML config and load it into a :class:`UserConfig`."""
    output_dir: Path = tmp_path / 'out'
    config_path: Path = tmp_path / 'config.yaml'
    config_path.write_text(
        _YAML_BODY_TEMPLATE.format(
            client_id=client_id,
            base_url=base_url,
            output_dir=output_dir,
        )
    )
    return UserConfig.from_yaml(config_path)


def _build_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retry_config: RetryConfig | None = None,
    clock: Clock | None = None,
) -> HttpTransport:
    """Build an ``HttpTransport`` routing every send through ``handler``.

    Accepts an optional ``clock`` so tests that exercise token expiry
    can pass a :class:`FrozenClock` and assert exact instants. Tests
    that don't care about time get :class:`SystemClock` by default.
    """
    mock_transport: httpx.MockTransport = httpx.MockTransport(handler)
    client: httpx.Client = httpx.Client(transport=mock_transport)
    return HttpTransport(
        client=client,
        retry_config=retry_config
        if retry_config is not None
        else RetryConfig(max_attempts=1),
        clock=clock if clock is not None else SystemClock(),
    )


@pytest.fixture
def user_config(tmp_path: Path) -> UserConfig:
    return _build_user_config(tmp_path)


@pytest.fixture
def silenced_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry waits instantaneous so retry tests don't block."""

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(time, 'sleep', _no_sleep)


class _CallCountingHandler:
    """Handler wrapper that records each incoming request for later assertions."""

    def __init__(
        self, inner_handler: Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self._inner_handler: Callable[[httpx.Request], httpx.Response] = inner_handler
        self.received_requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received_requests.append(request)
        return self._inner_handler(request)

    @property
    def call_count(self) -> int:
        return len(self.received_requests)


def _always_ok_handler(
    request: httpx.Request,
) -> httpx.Response:
    return httpx.Response(200, content=_token_payload())


# =============================================================================
# Caching behavior
# =============================================================================


class TestCaching:
    def test_first_call_fetches_and_returns_token(
        self, user_config: UserConfig
    ) -> None:
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            token: str = manager.get_valid_token()
        finally:
            transport.client.close()

        assert token == _TEST_ACCESS_TOKEN
        assert handler.call_count == 1

    def test_second_call_uses_cache(self, user_config: UserConfig) -> None:
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            first_token: str = manager.get_valid_token()
            second_token: str = manager.get_valid_token()
        finally:
            transport.client.close()

        assert first_token == second_token == _TEST_ACCESS_TOKEN
        # One network call for the initial fetch; the cached value was
        # served on the second request.
        assert handler.call_count == 1

    def test_expired_token_triggers_refresh(
        self,
        user_config: UserConfig,
    ) -> None:
        call_tokens: list[str] = ['first-token', 'second-token']
        issued_index: int = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal issued_index
            payload: bytes = _token_payload(access_token=call_tokens[issued_index])
            issued_index += 1
            return httpx.Response(200, content=payload)

        handler = _CallCountingHandler(_handler)
        fake_now: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=fake_now)
        transport: HttpTransport = _build_transport(handler, clock=clock)
        manager: TokenManager = TokenManager(user_config, transport)

        try:
            first_token: str = manager.get_valid_token()

            # Advance the clock past the token's expiry so the next
            # call must fetch again. ``_TEST_EXPIRES_IN`` seconds after
            # the first fetch is the exact expiry instant.
            clock.advance(timedelta(seconds=_TEST_EXPIRES_IN + 1))
            second_token: str = manager.get_valid_token()
        finally:
            transport.client.close()

        assert first_token == 'first-token'
        assert second_token == 'second-token'
        assert handler.call_count == 2

    def test_refresh_fires_exactly_at_skew_boundary(
        self,
        user_config: UserConfig,
    ) -> None:
        # Expiry check is inclusive: at ``_expiry_utc - skew`` the manager
        # refreshes. Crossing that boundary from "clearly inside the
        # skew window" back to "clearly outside" would change behavior
        # users observe, so the test pins the exact instant.
        call_tokens: list[str] = ['first-token', 'second-token']
        issued_index: int = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal issued_index
            payload: bytes = _token_payload(access_token=call_tokens[issued_index])
            issued_index += 1
            return httpx.Response(200, content=payload)

        handler = _CallCountingHandler(_handler)
        fake_now: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=fake_now)
        transport: HttpTransport = _build_transport(handler, clock=clock)
        manager: TokenManager = TokenManager(user_config, transport)

        try:
            manager.get_valid_token()

            # First fetch issued at ``fake_now``; expiry is
            # fake_now + 3600s. Advance the clock to exactly
            # (expiry - skew) so ``_needs_refresh`` returns True.
            clock.advance(timedelta(seconds=_TEST_EXPIRES_IN - _REFRESH_SKEW_SECONDS))
            manager.get_valid_token()
        finally:
            transport.client.close()

        # Two fetches: one at the initial ``get_valid_token``, one at
        # the exact skew boundary.
        assert handler.call_count == 2


# =============================================================================
# Refresh-log discrimination
# =============================================================================


class TestRefreshLogging:
    """
    The manager logs distinct messages for the three structurally
    different states that all reach the refresh path: an initial fetch
    on a fresh manager, a proactive refresh inside the skew window,
    and a reactive refresh after actual expiry. Before this fix all
    three logged the same generic ``cache miss or near-expiry`` line,
    which read as diagnostic language for an unexpected condition
    even on normal startup.
    """

    @staticmethod
    @pytest.fixture
    def propagating_pyholman_logger(monkeypatch: pytest.MonkeyPatch) -> None:
        # Earlier tests in the run may have invoked the real
        # ``setup_logger`` which flips ``pyholman.propagate=False``.
        # That stops caplog (which attaches to the root logger) from
        # observing pyholman output. Force propagation back on for the
        # duration of these tests so the log lines we care about are
        # captured deterministically.
        package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
        monkeypatch.setattr(package_logger, 'propagate', True)

    @staticmethod
    def _two_token_handler() -> _CallCountingHandler:
        # Hands out a different token on each call so a refresh path
        # can be confirmed by inspecting the returned strings.
        call_tokens: list[str] = ['first-token', 'second-token']
        issued_index: int = 0

        def _handler(_request: httpx.Request) -> httpx.Response:
            nonlocal issued_index
            payload: bytes = _token_payload(access_token=call_tokens[issued_index])
            issued_index += 1
            return httpx.Response(200, content=payload)

        return _CallCountingHandler(_handler)

    def test_first_call_logs_initial_fetch(
        self,
        user_config: UserConfig,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
                manager.get_valid_token()
        finally:
            transport.client.close()

        debug_messages: list[str] = [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.DEBUG
        ]
        # The new "initial token" line is present, and the old generic
        # "cache miss or near-expiry" wording must not appear — the
        # whole point of the change is that startup is not a "miss".
        assert 'Fetching initial token.' in debug_messages
        assert not any('cache miss or near-expiry' in message for message in debug_messages)

    def test_near_expiry_refresh_logs_skew_window_with_seconds_remaining(
        self,
        user_config: UserConfig,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        handler: _CallCountingHandler = self._two_token_handler()
        fake_now: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=fake_now)
        transport: HttpTransport = _build_transport(handler, clock=clock)
        manager: TokenManager = TokenManager(user_config, transport)

        try:
            # Populate the cache so the second call is a refresh path,
            # not an initial fetch. Clear caplog after so only the
            # second call's log lines are asserted on.
            manager.get_valid_token()
            caplog.clear()

            # Advance to inside the skew window: at this instant the
            # token has 5 seconds of real validity remaining (which is
            # less than the 30s skew, so a refresh is triggered) but
            # is not yet past actual expiry.
            seconds_inside_skew_window: float = _TEST_EXPIRES_IN - 5.0
            clock.advance(timedelta(seconds=seconds_inside_skew_window))

            with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
                manager.get_valid_token()
        finally:
            transport.client.close()

        skew_window_lines: list[logging.LogRecord] = [
            record
            for record in caplog.records
            if 'within refresh skew window' in record.getMessage()
        ]
        assert len(skew_window_lines) == 1
        assert skew_window_lines[0].levelno == logging.DEBUG
        # The "X.Xs until expiry" detail is included; the value is the
        # actual time-to-expiry, not the time-to-refresh-threshold.
        assert '5.0s until expiry' in skew_window_lines[0].getMessage()
        # And neither of the other two states' lines appears.
        all_messages: list[str] = [record.getMessage() for record in caplog.records]
        assert not any('Fetching initial token.' in message for message in all_messages)
        assert not any('Token expired' in message for message in all_messages)

    def test_past_expiry_refresh_logs_expired_message(
        self,
        user_config: UserConfig,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        handler: _CallCountingHandler = self._two_token_handler()
        fake_now: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=fake_now)
        transport: HttpTransport = _build_transport(handler, clock=clock)
        manager: TokenManager = TokenManager(user_config, transport)

        try:
            manager.get_valid_token()
            caplog.clear()

            # Advance past the actual expiry instant. ``+1`` puts the
            # clock one second beyond expiry — clearly in the
            # past-expiry branch and not just inside the skew window.
            clock.advance(timedelta(seconds=_TEST_EXPIRES_IN + 1))

            with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
                manager.get_valid_token()
        finally:
            transport.client.close()

        expired_lines: list[logging.LogRecord] = [
            record
            for record in caplog.records
            if record.getMessage() == 'Token expired; refreshing.'
        ]
        assert len(expired_lines) == 1
        assert expired_lines[0].levelno == logging.DEBUG
        # And the skew-window phrasing must not appear — it would
        # claim the token still has positive time remaining, which is
        # wrong on this code path.
        all_messages: list[str] = [record.getMessage() for record in caplog.records]
        assert not any(
            'within refresh skew window' in message for message in all_messages
        )

    def test_cache_hit_logs_remaining_seconds_unchanged(
        self,
        user_config: UserConfig,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        # The cache-hit log line is unchanged by this fix; pin it so a
        # future refactor of the get_valid_token discrimination cannot
        # silently regress it.
        del propagating_pyholman_logger
        handler: _CallCountingHandler = _CallCountingHandler(_always_ok_handler)
        fake_now: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=fake_now)
        transport: HttpTransport = _build_transport(handler, clock=clock)
        manager: TokenManager = TokenManager(user_config, transport)

        try:
            manager.get_valid_token()
            caplog.clear()

            # Stay well clear of the skew window: advance only a few
            # seconds. The second call is a cache hit.
            clock.advance(timedelta(seconds=10))
            with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
                manager.get_valid_token()
        finally:
            transport.client.close()

        cache_hit_lines: list[logging.LogRecord] = [
            record
            for record in caplog.records
            if 'Token cache hit;' in record.getMessage()
        ]
        assert len(cache_hit_lines) == 1
        assert cache_hit_lines[0].levelno == logging.DEBUG
        # No refresh-path lines emitted.
        all_messages: list[str] = [record.getMessage() for record in caplog.records]
        assert not any('Fetching initial token.' in message for message in all_messages)
        assert not any('Token expired' in message for message in all_messages)
        assert not any(
            'within refresh skew window' in message for message in all_messages
        )


# =============================================================================
# Auth header shape
# =============================================================================


class TestAuthHeader:
    def test_get_auth_header_returns_bearer_dict(self, user_config: UserConfig) -> None:
        transport: HttpTransport = _build_transport(_always_ok_handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            header: dict[str, str] = manager.get_auth_header()
        finally:
            transport.client.close()

        assert header == {'Authorization': f'Bearer {_TEST_ACCESS_TOKEN}'}


# =============================================================================
# Error handling
# =============================================================================


class TestErrorHandling:
    def test_401_raises_holman_error_and_leaves_cache_untouched(
        self, user_config: UserConfig
    ) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, content=b'unauthorized')

        handler = _CallCountingHandler(_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            with pytest.raises(HolmanError) as excinfo:
                manager.get_valid_token()
        finally:
            transport.client.close()

        # 401 is not retryable — exactly one attempt was made.
        assert handler.call_count == 1
        assert excinfo.value.status_code == 401
        # Cache fields were never populated.
        assert manager._cached_token is None
        assert manager._expiry_utc is None

    def test_500_then_200_succeeds_when_retry_budget_allows(
        self,
        user_config: UserConfig,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep  # fixture applied; value unused
        call_count: int = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, content=b'first flake')
            return httpx.Response(200, content=_token_payload())

        transport: HttpTransport = _build_transport(
            _handler, retry_config=RetryConfig(max_attempts=2)
        )
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            token: str = manager.get_valid_token()
        finally:
            transport.client.close()

        # Confirms retry still works through the transport-layer
        # plumbing even though TokenManager no longer wires it.
        assert token == _TEST_ACCESS_TOKEN
        assert call_count == 2

    def test_malformed_response_body_raises_holman_error_chained(
        self, user_config: UserConfig
    ) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'{"not":"a token"}')

        transport: HttpTransport = _build_transport(_handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            with pytest.raises(HolmanError) as excinfo:
                manager.get_valid_token()
        finally:
            transport.client.close()

        # The underlying ``ValidationError`` is preserved as the cause
        # so a caller inspecting the chain can tell the failure was a
        # shape mismatch, not a network error.
        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'

    def test_non_bearer_token_type_raises_holman_error(
        self, user_config: UserConfig
    ) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_token_payload(token_type='MAC'))

        transport: HttpTransport = _build_transport(_handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            with pytest.raises(HolmanError) as excinfo:
                manager.get_valid_token()
        finally:
            transport.client.close()

        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'


# =============================================================================
# Request shape
# =============================================================================


class TestRequestShape:
    def test_form_body_contains_client_credentials_fields(
        self, user_config: UserConfig
    ) -> None:
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            manager.get_valid_token()
        finally:
            transport.client.close()

        sent_request: httpx.Request = handler.received_requests[0]
        content_type: str = sent_request.headers['Content-Type']
        assert content_type.startswith('application/x-www-form-urlencoded')

        parsed_body: dict[str, list[str]] = parse_qs(
            sent_request.content.decode('utf-8')
        )
        assert parsed_body == {
            'grant_type': ['client_credentials'],
            'client_id': ['my-client-id'],
            'client_secret': ['test-secret-value'],
        }

    def test_target_url_ends_with_token_endpoint_path(
        self, user_config: UserConfig
    ) -> None:
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(user_config, transport)
        try:
            manager.get_valid_token()
        finally:
            transport.client.close()

        sent_request: httpx.Request = handler.received_requests[0]
        assert str(sent_request.url) == (
            f'https://api.holman.solutions{_TOKEN_ENDPOINT_PATH}'
        )

    def test_base_url_with_trailing_slash_yields_same_url(self, tmp_path: Path) -> None:
        # A base URL with a trailing slash and one without must produce
        # the same target URL. That's the point of routing through
        # ``build_url`` rather than open-coding concatenation.
        config_with_trailing_slash: UserConfig = _build_user_config(
            tmp_path, base_url='https://api.holman.solutions/'
        )
        handler = _CallCountingHandler(_always_ok_handler)
        transport: HttpTransport = _build_transport(handler)
        manager: TokenManager = TokenManager(config_with_trailing_slash, transport)
        try:
            manager.get_valid_token()
        finally:
            transport.client.close()

        sent_request: httpx.Request = handler.received_requests[0]
        assert str(sent_request.url) == (
            f'https://api.holman.solutions{_TOKEN_ENDPOINT_PATH}'
        )
