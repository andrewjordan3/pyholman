# tests/test_client.py
"""Tests for :class:`HolmanClient`."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import Field

from pyholman import HolmanError, RateLimitError, TransientHolmanError
from pyholman._auth import TokenManager
from pyholman._client import HolmanClient
from pyholman._config import UserConfig
from pyholman._core import QueryInputBase, ResponseModel
from pyholman._transport import HttpTransport
from tests._helpers.http import (
    _install_mock_transport,
    _page_body,
    _RecordingHandler,
)

__all__: list[str] = []


# =============================================================================
# Test-local QueryInputBase subclass and response item model
# =============================================================================


class _TestItem(ResponseModel):
    """Minimal response-item model used by the test query below."""

    item_id: int = Field(alias='itemId')
    label: str


_TEST_ENDPOINT_PATH: str = '/CustomerDataAPI/test/basic-query'


@dataclass(frozen=True, slots=True, kw_only=True)
class _TestQuery(QueryInputBase[_TestItem]):
    """Test-local query — real endpoint modules arrive in later prompts."""

    endpoint_path: ClassVar[str] = _TEST_ENDPOINT_PATH
    response_item_type: ClassVar[type[ResponseModel]] = _TestItem


# =============================================================================
# Test fixtures
# =============================================================================


_TOKEN_ENDPOINT_PATH: str = '/sso/sts/connect/token'
_TOKEN_RESPONSE_BODY: bytes = (
    b'{"access_token":"test-token",'
    b'"token_type":"Bearer",'
    b'"expires_in":3600,'
    b'"scope":"read"}'
)


def _default_item(item_id: int) -> dict[str, object]:
    """A minimal item dict matching ``_TestItem``."""
    return {'itemId': item_id, 'label': f'label-{item_id}'}


_YAML_BODY_TEMPLATE: str = dedent(
    """\
    credentials:
      client_id: 'my-client-id'
    api:
      base_url: 'https://api.holman.solutions'
      page_size: {page_size}
    fleet:
      organization_id: 'ORG1'
      lessee_codes:
        - 'ABCD'
    working_directory: '{output_dir}'
    resources:
      - name: vehicles
    """
)


def _build_user_config(tmp_path: Path, *, page_size: int = 200) -> UserConfig:
    """Write a minimal YAML config and load it into a :class:`UserConfig`."""
    output_dir: Path = tmp_path / 'out'
    config_path: Path = tmp_path / 'config.yaml'
    config_path.write_text(
        _YAML_BODY_TEMPLATE.format(page_size=page_size, output_dir=output_dir)
    )
    return UserConfig.from_yaml(config_path)


@pytest.fixture
def user_config(tmp_path: Path) -> UserConfig:
    return _build_user_config(tmp_path)


@pytest.fixture
def silenced_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry waits instantaneous so retry tests don't block."""

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(time, 'sleep', _no_sleep)


# =============================================================================
# Token responder shared across tests
# =============================================================================


def _always_token_response(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(200, content=_TOKEN_RESPONSE_BODY)


# =============================================================================
# Construction
# =============================================================================


class TestConstruction:
    def test_constructs_from_minimal_user_config(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler({_TOKEN_ENDPOINT_PATH: _always_token_response})
        _install_mock_transport(monkeypatch, handler)

        client: HolmanClient = HolmanClient(user_config)
        try:
            assert isinstance(client._transport, HttpTransport)
            assert isinstance(client._token_manager, TokenManager)
        finally:
            client.close()


# =============================================================================
# Context manager
# =============================================================================


class TestContextManager:
    def test_with_block_returns_self_and_closes_on_exit(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler({_TOKEN_ENDPOINT_PATH: _always_token_response})
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            assert isinstance(client, HolmanClient)
            # The underlying httpx client is open while inside the
            # ``with`` block.
            assert client._transport.client.is_closed is False

        # On exit the client must be closed so pooled connections are
        # released.
        assert client._transport.client.is_closed is True

    def test_exception_inside_with_block_propagates_and_client_closed(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler({_TOKEN_ENDPOINT_PATH: _always_token_response})
        _install_mock_transport(monkeypatch, handler)

        client_ref: list[HolmanClient] = []

        def _raising_body() -> None:
            with HolmanClient(user_config) as client:
                client_ref.append(client)
                raise RuntimeError('caller bug')

        with pytest.raises(RuntimeError, match='caller bug'):
            _raising_body()

        # ``__exit__`` must return None (not truthy) so the exception
        # propagates; the client should still be closed.
        assert client_ref[0]._transport.client.is_closed is True

    def test_close_is_idempotent(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler({_TOKEN_ENDPOINT_PATH: _always_token_response})
        _install_mock_transport(monkeypatch, handler)

        client: HolmanClient = HolmanClient(user_config)
        client.close()
        # Second call must not raise — users may forget and call close
        # explicitly after a ``with`` block.
        client.close()
        assert client._transport.client.is_closed is True


# =============================================================================
# send
# =============================================================================


def _default_query() -> _TestQuery:
    return _TestQuery(base_url='https://api.holman.solutions', lessee_codes=('ABCD',))


class TestSend:
    def test_happy_path_returns_typed_envelope(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_default_item(1), _default_item(2)],
                        total_count=2,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            response = client.send(_default_query())

        assert response.total_count == 2
        assert len(response.items) == 2
        # The class-getitem parameterization produced an envelope whose
        # items are ``_TestItem`` instances — the type narrowing is
        # what makes downstream DataFrame assembly work.
        assert all(isinstance(item, _TestItem) for item in response.items)
        assert response.items[0].item_id == 1
        assert response.items[0].label == 'label-1'
        assert response.page_info is not None
        assert response.page_info.total_pages == 1

    def test_send_attaches_bearer_authorization_header(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    200,
                    content=_page_body(items=[_default_item(1)], total_count=1),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            client.send(_default_query())

        data_requests: list[httpx.Request] = handler.requests_for_path(
            _TEST_ENDPOINT_PATH
        )
        assert len(data_requests) == 1
        # The header value is composed from the fake token response
        # issued at the top of this test (``access_token: 'test-token'``).
        assert data_requests[0].headers['Authorization'] == 'Bearer test-token'

    def test_send_uses_configured_page_size(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configured_page_size: int = 50
        user_config: UserConfig = _build_user_config(
            tmp_path, page_size=configured_page_size
        )
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_default_item(1)],
                        total_count=1,
                        page_size=configured_page_size,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            client.send(_default_query())

        sent_url: str = str(handler.requests_for_path(_TEST_ENDPOINT_PATH)[0].url)
        parsed_query: dict[str, list[str]] = parse_qs(urlsplit(sent_url).query)
        assert parsed_query['pageSize'] == [str(configured_page_size)]

    def test_send_passes_caller_page_number(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        requested_page: int = 3
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_default_item(requested_page)],
                        total_count=10,
                        page_number=requested_page,
                        total_pages=5,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            client.send(_default_query(), page_number=requested_page)

        sent_url: str = str(handler.requests_for_path(_TEST_ENDPOINT_PATH)[0].url)
        parsed_query: dict[str, list[str]] = parse_qs(urlsplit(sent_url).query)
        assert parsed_query['pageNumber'] == [str(requested_page)]

    def test_401_from_data_endpoint_raises_holman_error(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    401, content=b'unauthorized'
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:  # noqa: SIM117
            with pytest.raises(HolmanError) as excinfo:
                client.send(_default_query())

        assert excinfo.value.status_code == 401
        # 401 is not transient; it must not bubble up as a retryable
        # subclass or orchestrators will retry a credential problem
        # forever.
        assert type(excinfo.value) is HolmanError

    def test_500_with_retry_exhausted_raises_transient(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep
        # The shipped ``RetryConfig`` default is 5 attempts; every call
        # to the data endpoint returns 500 so the retry budget is
        # exhausted on every send.
        call_counter: dict[str, int] = {'count': 0}

        def _five_hundred(_request: httpx.Request) -> httpx.Response:
            call_counter['count'] += 1
            return httpx.Response(500, content=b'boom')

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _five_hundred,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:  # noqa: SIM117
            with pytest.raises(TransientHolmanError):
                client.send(_default_query())

        # Default retry budget is 5 attempts.
        assert call_counter['count'] == 5

    def test_malformed_body_raises_chained_holman_error(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: lambda request: httpx.Response(
                    200, content=b'{"not":"a page"}'
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:  # noqa: SIM117
            with pytest.raises(HolmanError) as excinfo:
                client.send(_default_query())

        assert excinfo.value.__cause__ is not None
        assert excinfo.value.__cause__.__class__.__name__ == 'ValidationError'
        # The endpoint description flows through to the error message.
        assert _TEST_ENDPOINT_PATH in str(excinfo.value)


# =============================================================================
# iter_pages
# =============================================================================


def _sequential_page_handler(
    *,
    total_pages: int,
    items_per_page: int = 2,
) -> Callable[[httpx.Request], httpx.Response]:
    """
    Return a data-endpoint handler that inspects ``pageNumber`` on the
    inbound URL and yields the corresponding page's items.

    Used by multi-page tests so each call reads the exact page number
    the client asked for, rather than relying on test-local mutable
    state.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        parsed_query: dict[str, list[str]] = parse_qs(urlsplit(str(request.url)).query)
        page_number: int = int(parsed_query['pageNumber'][0])
        start_id: int = (page_number - 1) * items_per_page + 1
        items: list[dict[str, object]] = [
            _default_item(start_id + offset) for offset in range(items_per_page)
        ]
        return httpx.Response(
            200,
            content=_page_body(
                items=items,
                total_count=total_pages * items_per_page,
                page_number=page_number,
                total_pages=total_pages,
            ),
        )

    return _handler


class TestIterPages:
    def test_single_page_yields_one_and_stops(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _sequential_page_handler(total_pages=1),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert len(pages) == 1
        assert pages[0].page_info is not None
        assert pages[0].page_info.total_pages == 1

    def test_multi_page_yields_each_in_order(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        total_pages: int = 3
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _sequential_page_handler(total_pages=total_pages),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert len(pages) == total_pages
        data_requests: list[httpx.Request] = handler.requests_for_path(
            _TEST_ENDPOINT_PATH
        )
        sent_page_numbers: list[int] = [
            int(parse_qs(urlsplit(str(req.url)).query)['pageNumber'][0])
            for req in data_requests
        ]
        assert sent_page_numbers == [1, 2, 3]

    def test_empty_query_yields_nothing(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Holman's empty-result envelope omits ``pageInfo`` and carries
        # ``message: "No data found."``.
        def _empty_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page_body(
                    items=[],
                    total_count=0,
                    total_pages=None,
                    message='No data found.',
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _empty_handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert pages == []

    def test_empty_page_past_end_terminates_cleanly(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Page 1 returns items; page 2 returns empty. Simulates Holman
        # advertising ``total_pages=2`` but serving an empty page 2 —
        # the client must still terminate rather than raise.
        call_counter: dict[str, int] = {'count': 0}

        def _handler(_request: httpx.Request) -> httpx.Response:
            call_counter['count'] += 1
            if call_counter['count'] == 1:
                return httpx.Response(
                    200,
                    content=_page_body(
                        items=[_default_item(1)],
                        total_count=5,
                        page_number=1,
                        total_pages=5,
                    ),
                )
            return httpx.Response(
                200,
                content=_page_body(
                    items=[],
                    total_count=5,
                    total_pages=None,
                    message='No data found.',
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert len(pages) == 1
        assert call_counter['count'] == 2

    def test_error_mid_iteration_yields_prior_pages_then_raises(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep
        call_counter: dict[str, int] = {'count': 0}

        def _handler(_request: httpx.Request) -> httpx.Response:
            call_counter['count'] += 1
            if call_counter['count'] == 1:
                return httpx.Response(
                    200,
                    content=_page_body(
                        items=[_default_item(1)],
                        total_count=10,
                        page_number=1,
                        total_pages=5,
                    ),
                )
            return httpx.Response(500, content=b'boom')

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        pages: list = []
        with HolmanClient(user_config) as client:
            iterator = client.iter_pages(_default_query())
            # Page 1 lands cleanly; page 2 retries and exhausts.
            pages.append(next(iterator))
            with pytest.raises(TransientHolmanError):
                next(iterator)

        assert len(pages) == 1
        # One fetch for page 1 plus the default retry budget (5) for
        # page 2.
        assert call_counter['count'] == 1 + 5

    def test_iter_pages_stops_when_items_present_but_page_info_missing(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Reachable safety net: Holman's envelope types ``page_info`` as
        # ``PageInfo | None``, and we've observed the ``None`` case on
        # empty queries. This test pins the defensive branch that kicks
        # in if a non-empty page ever arrives without pagination
        # metadata — the iterator must stop cleanly, not loop forever.
        call_counter: dict[str, int] = {'count': 0}

        def _handler(_request: httpx.Request) -> httpx.Response:
            call_counter['count'] += 1
            return httpx.Response(
                200,
                content=_page_body(
                    items=[_default_item(1)],
                    total_count=1,
                    total_pages=None,
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert len(pages) == 1
        assert pages[0].page_info is None
        assert pages[0].items[0].item_id == 1
        # Exactly one data-endpoint fetch: the iterator stopped after
        # the first page rather than looping.
        assert call_counter['count'] == 1


# =============================================================================
# Auth-token caching across HolmanClient operations
# =============================================================================


class TestAuthTokenCaching:
    def test_token_fetched_once_across_multiple_sends(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Three ``send`` calls should hit the data endpoint three times
        # and the auth endpoint exactly once — TokenManager's cache is
        # consumed correctly by HolmanClient.
        path_counters: dict[str, int] = {
            _TOKEN_ENDPOINT_PATH: 0,
            _TEST_ENDPOINT_PATH: 0,
        }

        def _counting_token(request: httpx.Request) -> httpx.Response:
            del request
            path_counters[_TOKEN_ENDPOINT_PATH] += 1
            return httpx.Response(200, content=_TOKEN_RESPONSE_BODY)

        def _counting_data(_request: httpx.Request) -> httpx.Response:
            path_counters[_TEST_ENDPOINT_PATH] += 1
            return httpx.Response(
                200,
                content=_page_body(
                    items=[_default_item(1)],
                    total_count=1,
                    total_pages=1,
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _counting_token,
                _TEST_ENDPOINT_PATH: _counting_data,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            client.send(_default_query())
            client.send(_default_query())
            client.send(_default_query())

        assert path_counters[_TOKEN_ENDPOINT_PATH] == 1
        assert path_counters[_TEST_ENDPOINT_PATH] == 3

    def test_token_fetched_once_across_iter_pages(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Iterating three pages should fetch the token once and hit the
        # data endpoint three times.
        path_counters: dict[str, int] = {
            _TOKEN_ENDPOINT_PATH: 0,
            _TEST_ENDPOINT_PATH: 0,
        }

        def _counting_token(request: httpx.Request) -> httpx.Response:
            del request
            path_counters[_TOKEN_ENDPOINT_PATH] += 1
            return httpx.Response(200, content=_TOKEN_RESPONSE_BODY)

        paging_handler = _sequential_page_handler(total_pages=3)

        def _counting_data(request: httpx.Request) -> httpx.Response:
            path_counters[_TEST_ENDPOINT_PATH] += 1
            return paging_handler(request)

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _counting_token,
                _TEST_ENDPOINT_PATH: _counting_data,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            pages: list = list(client.iter_pages(_default_query()))

        assert len(pages) == 3
        assert path_counters[_TOKEN_ENDPOINT_PATH] == 1
        assert path_counters[_TEST_ENDPOINT_PATH] == 3


# =============================================================================
# 429 retry-exhaustion surfacing
# =============================================================================


class TestRateLimitExhaustion:
    def test_429_exhaustion_surfaces_rate_limit_error(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        # Tenacity is configured with ``reraise=True``, so on retry
        # exhaustion the last captured exception surfaces verbatim.
        # For a 429 that exhausts, that's ``RateLimitError`` — not a
        # plain ``TransientHolmanError`` and not a tenacity
        # ``RetryError`` wrapper. This test pins the behavior
        # documented on ``HolmanClient.send``.
        del silenced_sleep
        call_counter: dict[str, int] = {'count': 0}

        def _always_rate_limited(_request: httpx.Request) -> httpx.Response:
            call_counter['count'] += 1
            return httpx.Response(
                429,
                headers={'Retry-After': '1'},
                content=b'slow down',
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _always_rate_limited,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:  # noqa: SIM117
            with pytest.raises(RateLimitError) as excinfo:
                client.send(_default_query())

        # The exact RateLimitError subclass must propagate — callers
        # catching the subclass specifically (to read
        # ``retry_after_seconds``) rely on this.
        assert type(excinfo.value) is RateLimitError
        assert excinfo.value.retry_after_seconds == 1.0
        # Default retry budget is 5 attempts.
        assert call_counter['count'] == 5


# =============================================================================
# collect
# =============================================================================


class TestCollect:
    def test_empty_query_returns_empty_list(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _empty_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page_body(
                    items=[],
                    total_count=0,
                    total_pages=None,
                    message='No data found.',
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _empty_handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            items: list[_TestItem] = client.collect(_default_query())

        assert items == []

    def test_single_page_returns_items_in_order(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _sequential_page_handler(
                    total_pages=1, items_per_page=3
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            items: list[_TestItem] = client.collect(_default_query())

        assert [item.item_id for item in items] == [1, 2, 3]
        assert all(isinstance(item, _TestItem) for item in items)

    def test_multi_page_concatenates_page_then_record_order(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        total_pages: int = 3
        items_per_page: int = 2
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _sequential_page_handler(
                    total_pages=total_pages, items_per_page=items_per_page
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:
            items: list[_TestItem] = client.collect(_default_query())

        # _sequential_page_handler numbers items (page-1)*items_per_page+1,
        # +2, ..., so page-then-record order is a contiguous 1..N range.
        assert [item.item_id for item in items] == list(
            range(1, total_pages * items_per_page + 1)
        )

    def test_errors_from_iter_pages_propagate(
        self,
        user_config: UserConfig,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep

        def _five_hundred(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b'boom')

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _TEST_ENDPOINT_PATH: _five_hundred,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with HolmanClient(user_config) as client:  # noqa: SIM117
            with pytest.raises(TransientHolmanError):
                client.collect(_default_query())
