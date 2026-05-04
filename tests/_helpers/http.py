# tests/_helpers/http.py
"""
Shared HTTP test helpers for the pyholman test suite.

These helpers are test-internal — they are not part of the pyholman
public API. They are extracted into this module to avoid duplicating the
same plumbing across multiple test files:

- :class:`_RecordingHandler` records every request seen by an
  :class:`httpx.MockTransport` so tests can assert against URL, headers,
  body, and call ordering.
- :func:`_install_mock_transport` swaps
  :func:`pyholman._client.client.build_transport` for a factory that
  returns a mock-backed :class:`HttpTransport`.
- :func:`_page_body` builds a Holman-shaped paginated response JSON
  envelope.
"""

import json
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
import pytest

import pyholman._client.client as client_module
from pyholman._clock import SystemClock
from pyholman._config import RetryConfig
from pyholman._transport import HttpTransport

__all__: list[str] = []


class _RecordingHandler:
    """
    Dispatch-by-path handler that records every incoming request.

    Instances act as the callable handler passed to
    :class:`httpx.MockTransport`. They look up a per-path responder in
    the supplied mapping and append every request seen — including
    requests with no matching path, before raising — to
    :attr:`received_requests` so tests can make assertions about call
    counts, ordering, headers, and bodies.

    Args:
        path_to_response: Map of URL path → callable that produces an
            :class:`httpx.Response` for a given request. Each entry is
            a callable so tests can sequence multiple responses against
            the same path (e.g. 500 then 200 across retries, or page 1
            then page 2).
    """

    def __init__(
        self,
        path_to_response: dict[str, Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        self._path_to_response: dict[str, Callable[[httpx.Request], httpx.Response]] = (
            path_to_response
        )
        self.received_requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """
        Record ``request`` and dispatch to the per-path responder.

        Args:
            request: The incoming :class:`httpx.Request` from the
                mock transport.

        Returns:
            The :class:`httpx.Response` produced by the registered
            responder for the request's URL path.

        Raises:
            AssertionError: When no responder is registered for the
                request's URL path. An unrouted path is a test-author
                error — failing loudly is preferable to a silent
                default that could mask a missing fixture.

        Side Effects:
            Appends ``request`` to :attr:`received_requests` before
            dispatching (or raising), so tests can inspect unmatched
            requests too.
        """
        self.received_requests.append(request)
        path: str = urlsplit(str(request.url)).path
        handler: Callable[[httpx.Request], httpx.Response] | None = (
            self._path_to_response.get(path)
        )
        if handler is None:
            raise AssertionError(f'No handler registered for path {path!r}')
        return handler(request)

    def requests_for_path(self, path: str) -> list[httpx.Request]:
        """
        Return every captured request whose URL path equals ``path``.

        Args:
            path: The URL path component to filter on (no scheme, host,
                or query string).

        Returns:
            The recorded requests, in arrival order, whose URL path
            equals ``path``.
        """
        return [
            captured
            for captured in self.received_requests
            if urlsplit(str(captured.url)).path == path
        ]


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    captured_api_configs: list[object] | None = None,
) -> None:
    """
    Replace :func:`pyholman._client.client.build_transport` with a mock factory.

    Monkeypatching the factory is the narrowest injection point: the
    real :class:`HolmanClient` still runs, using the real
    :class:`TokenManager` and the real ``send_request`` — only the HTTP
    boundary is stubbed out. The real retry config from
    ``user_config.retry`` is preserved when the caller supplies a
    :class:`RetryConfig`, so retry behavior through ``send_request``
    matches production.

    Args:
        monkeypatch: The pytest monkeypatch fixture that owns the
            replacement so it is reverted at test teardown.
        handler: A callable matching the
            :class:`httpx.MockTransport` handler signature, used to
            produce responses for every request the client makes.
        captured_api_configs: Optional list into which the patched
            factory will append each call's ``api_config`` argument.
            Lets a test assert on what the production code flowed
            through to the transport factory. ``None`` (the default)
            disables capture entirely.

    Side Effects:
        Patches the ``build_transport`` attribute on
        :mod:`pyholman._client.client` for the duration of the calling test.
    """

    def _build_transport_mock(
        api_config: object,
        retry_config: object,
        *,
        clock: object,
    ) -> HttpTransport:
        if captured_api_configs is not None:
            captured_api_configs.append(api_config)
        del clock  # SystemClock is fine for non-time-dependent tests.
        mock_transport: httpx.MockTransport = httpx.MockTransport(handler)
        httpx_client: httpx.Client = httpx.Client(transport=mock_transport)
        effective_retry: RetryConfig = (
            retry_config
            if isinstance(retry_config, RetryConfig)
            else RetryConfig(max_attempts=1)
        )
        return HttpTransport(
            client=httpx_client,
            retry_config=effective_retry,
            clock=SystemClock(),
        )

    monkeypatch.setattr(client_module, 'build_transport', _build_transport_mock)


def _page_body(  # noqa: PLR0913 — kwargs mirror the response envelope keys; bundling them adds noise without saving args.
    *,
    items: list[dict[str, object]],
    total_count: int,
    page_number: int = 1,
    page_size: int = 200,
    total_pages: int | None = 1,
    message: str | None = None,
) -> bytes:
    """
    Build a Holman-shaped paginated response JSON body.

    Args:
        items: The page's items, each already shaped to its
            response-item alias schema.
        total_count: ``totalCount`` envelope value — the total number
            of items across all pages.
        page_number: ``pageInfo.pageNumber`` value. Defaults to 1.
        page_size: ``pageInfo.pageSize`` value. Defaults to 200.
        total_pages: ``pageInfo.totalPages`` value. Pass ``None`` to
            omit the entire ``pageInfo`` block — used by tests that
            exercise the "no pagination metadata" branch.
        message: Optional ``message`` envelope value. ``None`` (the
            default) omits the field entirely.

    Returns:
        The JSON envelope as UTF-8 encoded bytes, ready to be passed
        as ``httpx.Response(content=...)``.
    """
    payload: dict[str, object] = {
        'statusCode': 200,
        'totalCount': total_count,
        'items': items,
    }
    if total_pages is not None:
        payload['pageInfo'] = {
            'pageNumber': page_number,
            'pageSize': page_size,
            'totalPages': total_pages,
            'lastChangeRecordId': None,
        }
    if message is not None:
        payload['message'] = message
    return json.dumps(payload).encode('utf-8')
