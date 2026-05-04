# src/pyholman/_config/api.py
"""Holman API endpoint section of the user configuration."""

from pydantic import Field, HttpUrl

from pyholman._core import FrozenModel

__all__: list[str] = ['ApiConfig']


# Production endpoint. Default for ``ApiConfig.base_url`` so QA-only
# users override explicitly while the common case is no-arg
# constructible. The trailing slash matches Pydantic's ``HttpUrl``
# normalization, so the literal here and the post-validation form
# compare equal under ``str()``.
_PRODUCTION_BASE_URL: HttpUrl = HttpUrl('https://api.holman.solutions/')


class ApiConfig(FrozenModel):
    """
    Holman API endpoint configuration.

    Holman exposes two base URLs:

        - Production: ``https://api.holman.solutions`` (default)
        - QA (stg):   ``https://api.stg.holman.solutions``

    The base URL is stored as ``pydantic.HttpUrl`` so a malformed string
    (missing scheme, invalid host) fails at load time rather than at
    request time. Production is the default; QA users override
    ``base_url`` explicitly.

    Attributes:
        base_url: Scheme + host for the Holman API. Defaults to the
            production endpoint ``https://api.holman.solutions/``.
            QA users override with the ``stg`` host.
        page_size: Items requested per paginated call. Holman's developer
            guide documents a default of 200 and a server-side cap of 1000;
            the bounds here mirror that contract. Kept in config rather
            than on the query so a single deployment can tune it without
            touching endpoint code.
        use_truststore: Whether the HTTP client should trust the host's
            certificate store (via the ``truststore`` package) instead of
            the bundled ``certifi`` roots. Defaults to ``False`` so the
            library works out of the box; flip to ``True`` in deployments
            sitting behind an MITM corporate proxy (Zscaler, etc.) that
            presents an internally-signed certificate.
    """

    base_url: HttpUrl = _PRODUCTION_BASE_URL
    page_size: int = Field(default=200, ge=1, le=1000)
    use_truststore: bool = False
