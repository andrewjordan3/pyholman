# src/pyholman/_transport/factory.py
"""
Factory for the :class:`HttpTransport` bundle used by every pyholman caller.

:func:`build_transport` centralizes three concerns:

    1. **Trust store selection.** When ``ApiConfig.use_truststore`` is
       set, certificate verification is routed through the operating
       system's native trust store (via :mod:`truststore`) so corporate
       MITM proxies with an internally-signed root work without disabling
       verification. Otherwise httpx falls back to its bundled certifi
       roots.
    2. **Timeouts.** Connect, read, write, and pool timeouts are pinned
       to module-private constants. They are not exposed on
       :class:`ApiConfig` because no deployment has asked for tuning yet
       — promoting them to user config would be configurability nobody
       requested. If a real need surfaces, the constants move to
       :class:`ApiConfig` in one focused change.
    3. **User-Agent.** A ``pyholman/<version>`` header is set on the
       client so Holman's support team can identify the source of
       traffic when investigating an issue. The version string follows
       the same ``importlib.metadata`` lookup pattern that
       ``storage/metadata.py`` already uses, with an ``'unknown'``
       fallback when the package is not installed (running from a
       source checkout without ``pip install -e``).

Authentication headers are deliberately *not* set here. The OAuth2
bearer is per-request and rotates inside ``TokenManager``; attaching
it to the long-lived client would tie token rotation to client
construction.

The retry policy travels on the returned :class:`HttpTransport`
alongside the client so :func:`pyholman._transport.send_request` can
apply it uniformly without every caller having to remember to pass it.
"""

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Final

import httpx

from pyholman._clock import Clock
from pyholman._config import ApiConfig, RetryConfig
from pyholman._core.constants import PACKAGE_NAME
from pyholman._transport.ssl import build_truststore_ssl_context
from pyholman._transport.transport import HttpTransport

__all__: list[str] = ['build_transport']

logger: logging.Logger = logging.getLogger(__name__)


# =============================================================================
# Tuning constants
# =============================================================================
# Internal: not user config. If a deployment needs different values, we
# can promote the relevant ones to ``ApiConfig`` later in one focused
# change. Until then, these are good-enough defaults derived from the
# observed behavior of Holman's API and typical corporate networks.
# =============================================================================

# Maximum time to wait for a TCP connection (and TLS handshake) to
# complete. Ten seconds is generous enough to absorb Zscaler latency
# without making a misconfigured host hang the pipeline for a minute.
_CONNECT_TIMEOUT_SECONDS: Final[float] = 10.0

# Maximum time to wait for the server to send response data. Sized for
# Holman's larger paginated responses — the vehicle endpoint can take
# tens of seconds to assemble a full page under load.
_READ_TIMEOUT_SECONDS: Final[float] = 60.0

# Maximum time to wait while sending the request body. pyholman issues
# only small JSON bodies (auth payloads, query parameters serialized
# into the URL), so ten seconds is comfortable.
_WRITE_TIMEOUT_SECONDS: Final[float] = 10.0

# Maximum time to wait for a free connection from the pool. With
# pyholman's single-threaded request pattern this should never block;
# the timeout is short on purpose so a future bug that exhausts the
# pool surfaces quickly.
_POOL_TIMEOUT_SECONDS: Final[float] = 10.0


# =============================================================================
# Version lookup for the User-Agent header
# =============================================================================

# Sentinel surfaced in the User-Agent when the package is not installed
# (running tests from a source checkout without ``pip install -e``).
# The User-Agent is diagnostic; a missing version must not break client
# construction.
_UNKNOWN_VERSION: Final[str] = 'unknown'


def _get_user_agent_string() -> str:
    """
    Return the ``User-Agent`` header value used by the pyholman client.

    Format: ``pyholman/<version>``, matching the convention most
    Python HTTP clients follow. The version is read via
    :func:`importlib.metadata.version`; if the package is not installed
    (source checkout without ``pip install -e``), the version falls back
    to ``'unknown'`` rather than failing, mirroring the
    ``get_pyholman_version`` helper in ``storage/metadata.py``.

    Returns:
        A ``User-Agent`` value of the form ``'pyholman/<version>'``.
    """
    try:
        package_version: str = version(PACKAGE_NAME)
    except PackageNotFoundError:
        logger.debug(
            '%s not installed; using %r in the User-Agent header.',
            PACKAGE_NAME,
            _UNKNOWN_VERSION,
        )
        package_version = _UNKNOWN_VERSION

    return f'{PACKAGE_NAME}/{package_version}'


def _build_httpx_client(api_config: ApiConfig) -> httpx.Client:
    """
    Construct the configured ``httpx.Client`` wrapped by ``HttpTransport``.

    Private helper: the public entry point is :func:`build_transport`,
    which additionally bundles the retry policy. Split out so the three
    construction concerns (verify wiring, timeouts, headers) live in
    one focused function rather than being inlined in the factory.

    Args:
        api_config: Source of the ``use_truststore`` flag. Only that
            one field is read here.

    Returns:
        An ``httpx.Client`` with the configured timeouts, verify
        context, and User-Agent header, but no authentication headers.

    Raises:
        RuntimeError: If ``api_config.use_truststore`` is ``True`` but
            the optional ``truststore`` package is not installed. The
            error message includes installation instructions.
    """
    timeout: httpx.Timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT_SECONDS,
        read=_READ_TIMEOUT_SECONDS,
        write=_WRITE_TIMEOUT_SECONDS,
        pool=_POOL_TIMEOUT_SECONDS,
    )
    headers: dict[str, str] = {'User-Agent': _get_user_agent_string()}

    if api_config.use_truststore:
        # Only pass ``verify`` when truststore is actually requested.
        # Omitting the argument leaves httpx on its default (certifi),
        # which is the documented out-of-the-box behavior; passing
        # ``verify=True`` explicitly would be equivalent but obscures
        # the difference at the call site.
        ssl_context = build_truststore_ssl_context()
        return httpx.Client(verify=ssl_context, timeout=timeout, headers=headers)

    return httpx.Client(timeout=timeout, headers=headers)


def build_transport(
    api_config: ApiConfig,
    retry_config: RetryConfig,
    *,
    clock: Clock,
) -> HttpTransport:
    """
    Build the :class:`HttpTransport` every pyholman caller uses.

    The returned bundle carries the configured ``httpx.Client``
    (timeouts, verify context, User-Agent header), the retry policy
    that :func:`pyholman._transport.send_request` applies on every
    call, and the :class:`~pyholman._clock.Clock` that time-dependent
    helpers (token-expiry, ``Retry-After`` HTTP-date arithmetic) read
    from. No ``base_url`` is pinned on the client:
    :meth:`QueryInputBase.url` returns fully-qualified URLs and the
    OAuth2 token endpoint sits on the same host at a different path,
    so a client-level base URL would obscure where each path comes from.

    The caller owns the lifetime of the embedded client. Close it (or
    use the client as a context manager) when done to release pooled
    connections.

    Args:
        api_config: The API section of the user configuration. Only
            ``use_truststore`` is read here. The factory takes
            ``ApiConfig`` rather than the full ``UserConfig`` because
            passing the latter would suggest the factory inspects
            unrelated sections (credentials, fleet, output) — it does
            not.
        retry_config: Retry policy stored on the returned transport.
            ``send_request`` reads it on every call; every call through
            this transport applies the same policy.
        clock: Time provider stored on the returned transport.
            Production callers pass :class:`~pyholman._clock.SystemClock`;
            tests pass :class:`~pyholman._clock.FrozenClock` for
            deterministic timing assertions.

    Returns:
        An :class:`HttpTransport` wrapping a fresh ``httpx.Client`` and
        carrying ``retry_config`` and ``clock``.

    Raises:
        RuntimeError: If ``api_config.use_truststore`` is ``True`` but
            the optional ``truststore`` package is not installed. The
            error message includes installation instructions. Raised
            from :func:`build_truststore_ssl_context`.
    """
    client: httpx.Client = _build_httpx_client(api_config)
    return HttpTransport(client=client, retry_config=retry_config, clock=clock)
