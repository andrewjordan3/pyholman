# src/pyholman/_transport/ssl.py
"""
SSL Context Factory using System Trust Store.

This module provides a factory function to create SSL contexts that verify
certificates using the operating system's native trust store, rather than
Python's default bundled certificates (certifi).

Primary Use Case:
    Corporate environments using aggressive proxies (like Zscaler) that act as
    Man-in-the-Middle (MITM) inspectors. These proxies re-encrypt traffic using
    a private Root CA that is installed in the Windows/macOS system store but
    is unknown to standard Python libraries.

    Without this module, requests fail with `SSLCertVerificationError`.
    With this module, Python trusts the corporate Root CA, enabling secure
    connectivity without disabling SSL verification.

Design Benefit: Optional Dependency
    The `truststore` library is imported lazily inside the factory function.
    This design ensures that the package remains usable in standard environments
    (e.g., Linux servers, containers) where `truststore` might not be installed.
    The package will only raise a RuntimeError if this specific function is
    explicitly called without the dependency present.

Dependencies:
    - truststore: Optional. Required only if this factory function is called.
      Install with: `pip install truststore`
"""

import ssl
from ssl import SSLContext

__all__: list[str] = ['build_truststore_ssl_context']


def build_truststore_ssl_context() -> SSLContext:
    """
    Create an SSLContext using truststore for system certificate validation.

    Constructs a `truststore.SSLContext` (which subclasses `ssl.SSLContext`)
    that routes certificate verification through the operating system's native
    trust store. This is the documented and intended usage of the truststore
    library; `ssl.create_default_context()` is not a substitute, as it returns
    a standard context that uses Python's bundled certifi roots and would not
    see the corporate Root CA.

    The explicit `PROTOCOL_TLS_CLIENT` argument is required by truststore's
    constructor and provides secure defaults for client-side TLS with
    automatic protocol negotiation and certificate verification.

    Returns:
        SSLContext: Configured SSLContext using OS trust store. The object
            is an instance of `truststore.SSLContext` (a subclass of
            `ssl.SSLContext`) and can be passed anywhere an `ssl.SSLContext`
            is accepted, including `httpx.Client(verify=...)`.

    Raises:
        RuntimeError: If the `truststore` package is not installed. The
            error message includes installation instructions.

    Notes:
        - Safe for library code (no global monkey-patching of the ssl module).
        - Lazy import keeps `truststore` an optional dependency.
        - `PROTOCOL_TLS_CLIENT` is the current, non-deprecated constant for
          client-side TLS; it replaced the now-deprecated version-specific
          constants (e.g., `PROTOCOL_TLSv1_2`) in Python 3.10.

    Example:
        >>> import httpx
        >>> ssl_context = build_truststore_ssl_context()
        >>> client = httpx.Client(verify=ssl_context)
    """
    try:
        import truststore  # noqa: PLC0415
    except ImportError as import_error:
        raise RuntimeError(
            'truststore is required to build a system trust store SSL context; '
            'install it with: pip install truststore'
        ) from import_error

    # truststore.SSLContext requires an explicit protocol argument; PROTOCOL_TLS_CLIENT
    # is the correct choice for client-side TLS (replaces deprecated version-specific constants).
    ssl_context: SSLContext = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl_context
