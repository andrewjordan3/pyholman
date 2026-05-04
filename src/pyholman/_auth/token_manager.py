# src/pyholman/_auth/token_manager.py
"""
OAuth2 client-credentials token lifecycle for the Holman API.

:class:`TokenManager` holds one in-memory bearer token, fetches it on
first use via the client-credentials grant, and refreshes proactively
when the current token is within :data:`_REFRESH_SKEW_SECONDS` of
expiring. Callers (``HolmanClient``) reach for
``get_auth_header()`` on every request; the manager decides whether
that call triggers a network round trip or returns the cached token.

Three design choices worth stating explicitly:

    1. **No retry wiring.** Retry is a property of the transport layer,
       not the manager. ``_fetch_token`` calls
       :func:`pyholman._transport.send_request`, which applies the
       policy from ``transport.retry_config`` internally. The manager
       holds a :class:`HttpTransport` and forwards requests; it does
       not know the retry budget exists.

    2. **Single in-memory slot.** There is no cache eviction, no
       multiple-tenant support, no disk persistence. The manager
       serves one set of credentials for the lifetime of one
       :class:`UserConfig`. More sophisticated lifetime management
       would be premature.

    3. **Proactive refresh with skew.** Waiting until the exact
       ``expires_in`` instant would produce a race where a request
       starts with a still-valid token but arrives after it expires.
       Refreshing when the cached expiry is within
       :data:`_REFRESH_SKEW_SECONDS` of "now" avoids that window; the
       30-second default is generous enough for typical corporate
       network latency and clock drift while still giving close to
       the full token lifetime of useful work per refresh.
"""

import logging
from datetime import datetime, timedelta
from typing import Final

import httpx

from pyholman._auth.token_response import TokenResponse
from pyholman._config import UserConfig
from pyholman._core.constants import AUTH_ENDPOINT_PATH, BEARER_SCHEME
from pyholman._strings import build_url
from pyholman._transport import (
    HttpTransport,
    parse_response_body,
    send_request,
)

__all__: list[str] = ['TokenManager']

logger: logging.Logger = logging.getLogger(__name__)


# =============================================================================
# Module-level constants
# =============================================================================

# Refresh a token when it has this many seconds or fewer left. Prevents
# a race where a request prepared with a "still valid" token arrives
# after the token has expired on the server. 30 seconds absorbs typical
# corporate-network round-trip latency plus a few seconds of clock skew
# without giving up meaningful useful-life per token.
_REFRESH_SKEW_SECONDS: Final[float] = 30.0


# =============================================================================
# TokenManager
# =============================================================================


class TokenManager:
    """
    In-memory cache and refresher for an OAuth2 bearer token.

    The manager is stateful across calls: the first ``get_valid_token``
    triggers a fetch; subsequent calls within the token's validity
    window return the cached value without touching the network.
    Instances are not thread-safe — pyholman is single-threaded by
    design and a lock would be dead weight.

    Attributes are private. The public surface is:
        - :meth:`get_valid_token` — return a fresh token string.
        - :meth:`get_auth_header` — return the ``Authorization`` header
          dict, building it from the result of ``get_valid_token``.
    """

    def __init__(
        self,
        user_config: UserConfig,
        transport: HttpTransport,
    ) -> None:
        """
        Construct a token manager.

        Args:
            user_config: The full user configuration. The manager reads
                ``user_config.api.base_url`` for URL construction and
                ``user_config.credentials`` for the client-credentials
                grant body; it does not inspect other sections.
            transport: The shared :class:`HttpTransport`. The manager
                sends through ``transport.client`` and relies on
                ``send_request`` to apply ``transport.retry_config``.
        """
        self._user_config: UserConfig = user_config
        self._transport: HttpTransport = transport
        self._cached_token: str | None = None
        self._expiry_utc: datetime | None = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_valid_token(self) -> str:
        """
        Return a non-expired access token, refreshing if necessary.

        Three states are discriminated at the log site so a reader of
        the run log can tell which one fired:

            - **Initial fetch** (``self._cached_token`` is ``None``):
              the manager has never fetched. Logged as
              ``Fetching initial token.``
            - **Near expiry** (cache populated, now within
              :data:`_REFRESH_SKEW_SECONDS` of expiry but not yet
              past it): proactive refresh. Logged with the seconds
              remaining for symmetry with the cache-hit line.
            - **Past expiry** (cache populated, now at or after the
              expiry instant): reactive refresh. Logged as
              ``Token expired; refreshing.``

        A cache hit (cache populated, outside the skew window) logs
        the seconds remaining and returns the cached token without a
        network round trip.

        Returns:
            The bearer token string.

        Raises:
            HolmanError: If the auth endpoint returns a non-2xx status
                (after retries), an unexpected response shape (missing
                fields, non-Bearer ``token_type``), or a transient
                failure that exceeds the retry budget. The error's
                ``status_code`` and ``response_body`` attributes carry
                the HTTP details when available.
        """
        if self._cached_token is None or self._expiry_utc is None:
            logger.debug('Fetching initial token.')
            self._refresh()
            return self._unsafe_cached_token()

        if self._needs_refresh():
            seconds_until_expiry: float = (
                self._expiry_utc - self._transport.clock.now_utc()
            ).total_seconds()
            if seconds_until_expiry <= 0:
                logger.debug('Token expired; refreshing.')
            else:
                logger.debug(
                    'Token within refresh skew window '
                    '(%.1fs until expiry); refreshing.',
                    seconds_until_expiry,
                )
            self._refresh()
            return self._unsafe_cached_token()

        remaining_seconds: float = self._seconds_until_expiry()
        logger.debug(
            'Token cache hit; %.1fs remaining before refresh threshold.',
            remaining_seconds,
        )
        return self._unsafe_cached_token()

    def get_auth_header(self) -> dict[str, str]:
        """
        Return the ``Authorization`` header for a pyholman API request.

        Format: ``{'Authorization': 'Bearer <token>'}``. Refreshes the
        cached token first if necessary via :meth:`get_valid_token`.

        Returns:
            A single-key dict suitable for merging into an
            ``httpx.Request`` headers mapping.

        Raises:
            HolmanError: Propagated from :meth:`get_valid_token`.
        """
        token: str = self.get_valid_token()
        return {'Authorization': f'{BEARER_SCHEME} {token}'}

    # -------------------------------------------------------------------------
    # Cache-state helpers
    # -------------------------------------------------------------------------

    def _needs_refresh(self) -> bool:
        """
        Return ``True`` when the cache is empty or within the skew window.

        Treats equality with the skew boundary as "needs refresh" — the
        check is inclusive (``>=``) because waiting for a strict ``>``
        inequality would leave a one-second window where neither a
        refresh nor a cache hit can be demonstrated, complicating tests
        and occasionally producing a just-expired request in the wild.
        """
        if self._cached_token is None or self._expiry_utc is None:
            return True
        refresh_threshold: datetime = self._expiry_utc - timedelta(
            seconds=_REFRESH_SKEW_SECONDS
        )
        return self._transport.clock.now_utc() >= refresh_threshold

    def _seconds_until_expiry(self) -> float:
        """
        Return the number of seconds until the cached token needs refresh.

        The caller checks ``_needs_refresh()`` first; this helper is
        only meaningful when the cache is populated. The return value
        is used for DEBUG logging, so a negative value (cache populated
        but already past the refresh threshold) is not an error here —
        the next ``get_valid_token`` will refresh.
        """
        assert self._expiry_utc is not None, (
            '_seconds_until_expiry called with empty cache; '
            'caller must check _needs_refresh first.'
        )
        refresh_threshold: datetime = self._expiry_utc - timedelta(
            seconds=_REFRESH_SKEW_SECONDS
        )
        return (refresh_threshold - self._transport.clock.now_utc()).total_seconds()

    def _unsafe_cached_token(self) -> str:
        """
        Return ``self._cached_token`` narrowed to ``str``.

        ``get_valid_token`` has already ensured the cache is populated
        (either by a just-completed refresh or by passing the
        ``_needs_refresh`` check). The helper exists to keep the type
        checker satisfied without scattering ``assert`` statements at
        every call site; the assert here documents the invariant at
        the language level rather than burying it in a raised error.
        """
        assert self._cached_token is not None, (
            '_unsafe_cached_token called with empty cache; '
            'caller must refresh or check _needs_refresh first.'
        )
        return self._cached_token

    # -------------------------------------------------------------------------
    # Refresh path
    # -------------------------------------------------------------------------

    def _refresh(self) -> None:
        """
        Fetch a new token and replace the cached value and expiry.

        Side Effects:
            Updates ``self._cached_token`` and ``self._expiry_utc`` on
            success. On failure, leaves both untouched — the exception
            propagates and the caller retries with the same cache
            state.
        """
        issued_at: datetime = self._transport.clock.now_utc()
        token_response: TokenResponse = self._fetch_token()
        self._cached_token = token_response.access_token
        self._expiry_utc = issued_at + timedelta(seconds=token_response.expires_in)
        logger.debug(
            'Token fetched; expires_in=%ds, scope=%s.',
            token_response.expires_in,
            token_response.scope,
        )

    def _fetch_token(self) -> TokenResponse:
        """
        POST the client-credentials grant and return the parsed response.

        The request body is ``application/x-www-form-urlencoded`` per
        RFC 6749 §4.4.2; httpx's ``data=`` parameter sets both the
        body encoding and the Content-Type header.

        Returns:
            A validated :class:`TokenResponse`.

        Raises:
            HolmanError: If the response body does not validate as a
                :class:`TokenResponse` — e.g., missing ``access_token``,
                ``expires_in=0``, or ``token_type='MAC'``. The original
                ``pydantic.ValidationError`` is chained via
                :func:`pyholman._transport.parse_response_body`, so the
                root cause is preserved. Transport and status failures
                propagate as their usual ``HolmanError`` subclasses
                without being re-wrapped here.
        """
        form_body: dict[str, str] = {
            'grant_type': 'client_credentials',
            'client_id': self._user_config.credentials.client_id,
            'client_secret': (
                self._user_config.credentials.client_secret.get_secret_value()
            ),
        }
        request: httpx.Request = self._transport.client.build_request(
            method='POST',
            url=self._token_endpoint_url(),
            data=form_body,
        )
        response: httpx.Response = send_request(self._transport, request)
        return parse_response_body(response, TokenResponse, 'the auth endpoint')

    def _token_endpoint_url(self) -> str:
        """
        Return the fully-qualified URL of Holman's OAuth2 token endpoint.

        Composed from ``user_config.api.base_url`` and
        :data:`pyholman._constants.AUTH_ENDPOINT_PATH`. Delegates to
        :func:`pyholman._strings.build_url` so slash normalization is
        identical to the way ``QueryInputBase.url`` builds endpoint
        URLs on the same host.
        """
        return build_url(
            base_url=str(self._user_config.api.base_url),
            path=AUTH_ENDPOINT_PATH,
        )
