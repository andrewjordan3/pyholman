# src/pyholman/_strings/url.py
"""
URL composition for pyholman.

Why not :func:`urllib.parse.urljoin` for :func:`build_url`:
    ``urljoin`` implements RFC 3986 relative-URL resolution, whose
    reference rules drop the base path when the second argument is
    absolute::

        >>> urljoin('https://example.com/api', '/foo')
        'https://example.com/foo'  # '/api' is gone

    pyholman always supplies a scheme+host base and a fixed absolute
    endpoint path; the RFC 3986 semantics are not what we want, and
    explicit concatenation is shorter and more predictable.
"""

import logging
from urllib.parse import urlencode

__all__: list[str] = ['build_url']

logger: logging.Logger = logging.getLogger(__name__)


def build_url(
    base_url: str,
    path: str,
    query_params: dict[str, str] | None = None,
) -> str:
    """
    Compose a full URL from a scheme+host base, a path, and query params.

    The base may or may not end with a slash; the path may or may not
    start with one. The function normalizes both so the result always
    has exactly one slash between them, never zero and never two.

    Query parameters are already-stringified values; the function
    percent-escapes them via :func:`urllib.parse.urlencode` and appends
    them after a ``?`` in the order the caller's dict iterates (Python
    3.7+ guarantees insertion order). An empty or ``None``
    ``query_params`` produces no ``?`` suffix at all.

    Args:
        base_url: Scheme and host (and optionally port) of the target,
            e.g. ``'https://api.holman.solutions'``. Trailing slash is
            tolerated.
        path: Absolute path on the host, e.g.
            ``'/sso/sts/connect/token'``. Leading slash is tolerated
            but not required.
        query_params: Already-stringified query parameters keyed by
            their wire names. ``None`` and the empty dict both produce
            a URL without a ``?``.

    Returns:
        The fully formed URL as a string.
    """
    normalized_base: str = base_url.rstrip('/')
    normalized_path: str = '/' + path.lstrip('/')
    full_url: str = normalized_base + normalized_path
    if query_params:
        full_url = full_url + '?' + urlencode(query_params)
    return full_url
