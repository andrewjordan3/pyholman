# tests/_transport/test_factory.py
"""Tests for the ``build_transport`` factory."""

import ssl
from typing import Any

import httpx
import pytest
from pydantic import HttpUrl

from pyholman._clock import SystemClock
from pyholman._config import ApiConfig, RetryConfig
from pyholman._transport import HttpTransport, build_transport
from pyholman._transport.factory import (
    _CONNECT_TIMEOUT_SECONDS,
    _POOL_TIMEOUT_SECONDS,
    _READ_TIMEOUT_SECONDS,
    _WRITE_TIMEOUT_SECONDS,
)

__all__: list[str] = []


def _build_api_config(*, use_truststore: bool) -> ApiConfig:
    """Construct an ``ApiConfig`` with only the fields these tests care about."""
    return ApiConfig(
        base_url=HttpUrl('https://api.holman.solutions'),
        use_truststore=use_truststore,
    )


def _extract_ssl_context(client: httpx.Client) -> Any:
    """
    Reach into the client's transport to retrieve the ``SSLContext`` it
    will use.

    httpx does not expose ``verify`` as a public attribute on the
    constructed client. The transport's connection pool is the
    documented carrier for the resolved context, and the attribute path
    has been stable since httpx 0.20+. The test mirrors how the
    ``httpx`` test suite itself inspects the same value.
    """
    transport: Any = client._transport
    return transport._pool._ssl_context


# =============================================================================
# Shape of the returned HttpTransport
# =============================================================================


class TestBuildTransportReturnShape:
    def test_returns_http_transport_instance(self) -> None:
        retry_config: RetryConfig = RetryConfig()
        clock: SystemClock = SystemClock()
        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=False),
            retry_config,
            clock=clock,
        )
        try:
            assert isinstance(transport, HttpTransport)
            assert isinstance(transport.client, httpx.Client)
            # The retry config and clock passed in must appear on the
            # returned transport by identity — the factory does not
            # copy or rebuild them.
            assert transport.retry_config is retry_config
            assert transport.clock is clock
        finally:
            transport.client.close()


# =============================================================================
# Truststore wiring
# =============================================================================


class TestTruststoreWiring:
    def test_use_truststore_true_wires_truststore_context(self) -> None:
        truststore_module = pytest.importorskip('truststore')

        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=True),
            RetryConfig(),
            clock=SystemClock(),
        )
        try:
            ssl_context: Any = _extract_ssl_context(transport.client)
            # ``truststore.SSLContext`` subclasses ``ssl.SSLContext``;
            # the subclass check confirms verification routes through
            # the OS trust store rather than certifi.
            assert isinstance(ssl_context, truststore_module.SSLContext)
        finally:
            transport.client.close()

    def test_use_truststore_false_uses_httpx_default_context(self) -> None:
        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=False),
            RetryConfig(),
            clock=SystemClock(),
        )
        try:
            ssl_context: Any = _extract_ssl_context(transport.client)
            # The httpx default for ``verify=True`` is a plain
            # ``ssl.SSLContext`` (certifi-backed). Confirming the type
            # is *exactly* the base class — not a truststore subclass —
            # is what differentiates this branch from the truststore one.
            assert isinstance(ssl_context, ssl.SSLContext)
            assert type(ssl_context) is ssl.SSLContext
        finally:
            transport.client.close()


# =============================================================================
# Timeouts
# =============================================================================


class TestTimeouts:
    def test_timeouts_match_module_constants(self) -> None:
        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=False),
            RetryConfig(),
            clock=SystemClock(),
        )
        try:
            timeout: httpx.Timeout = transport.client.timeout
            assert timeout.connect == _CONNECT_TIMEOUT_SECONDS
            assert timeout.read == _READ_TIMEOUT_SECONDS
            assert timeout.write == _WRITE_TIMEOUT_SECONDS
            assert timeout.pool == _POOL_TIMEOUT_SECONDS
        finally:
            transport.client.close()


# =============================================================================
# Headers
# =============================================================================


class TestHeaders:
    def test_user_agent_contains_pyholman_prefix(self) -> None:
        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=False),
            RetryConfig(),
            clock=SystemClock(),
        )
        try:
            user_agent: str = transport.client.headers['User-Agent']
            assert user_agent.startswith('pyholman/')
        finally:
            transport.client.close()

    def test_no_authorization_header_set(self) -> None:
        # Auth headers are added per-request by TokenManager / HolmanClient;
        # the client itself must not carry one or token rotation would be
        # silently bypassed.
        transport: HttpTransport = build_transport(
            _build_api_config(use_truststore=False),
            RetryConfig(),
            clock=SystemClock(),
        )
        try:
            assert 'Authorization' not in transport.client.headers
        finally:
            transport.client.close()
