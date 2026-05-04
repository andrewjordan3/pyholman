# src/pyholman/_transport/__init__.py
"""Internal transport layer: SSL context, retry policy, and exception types."""

from pyholman._transport.exceptions import (
    HolmanError,
    RateLimitError,
    TransientHolmanError,
)
from pyholman._transport.factory import build_transport
from pyholman._transport.request import parse_response_body, send_request
from pyholman._transport.retry_after import parse_retry_after_header
from pyholman._transport.ssl import build_truststore_ssl_context
from pyholman._transport.status import (
    raise_for_holman_status,
    translate_httpx_request_error,
)
from pyholman._transport.transport import HttpTransport

__all__: list[str] = [
    'HolmanError',
    'HttpTransport',
    'RateLimitError',
    'TransientHolmanError',
    'build_transport',
    'build_truststore_ssl_context',
    'parse_response_body',
    'parse_retry_after_header',
    'raise_for_holman_status',
    'send_request',
    'translate_httpx_request_error',
]
