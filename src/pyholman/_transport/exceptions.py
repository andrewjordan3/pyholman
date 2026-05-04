# src/pyholman/_transport/exceptions.py
"""
Exception hierarchy for pyholman transport errors.

The hierarchy is intentionally shallow — three classes — because real callers
typically want one of three things:

    1. Catch every pyholman HTTP error:   `except HolmanError`
    2. Handle transient errors specially: `except TransientHolmanError`
    3. Respect rate limits with server-supplied backoff: `except RateLimitError`

Classification rules:

    - HolmanError (base):      Any HTTP interaction with Holman's API that
                                didn't succeed. Includes both retryable and
                                non-retryable failures.

    - TransientHolmanError:    A failure that *may* succeed on retry. Raised
                                for timeouts, connection errors, HTTP 5xx
                                responses, and rate-limiting (429). The retry
                                decorator in retry.py catches this type.

    - RateLimitError:          HTTP 429. A subtype of TransientHolmanError
                                that carries the server's suggested wait
                                (``retry_after_seconds``). The retry wait
                                strategy prefers this value over exponential
                                backoff when it is present.

Non-retryable client errors (HTTP 4xx other than 429) raise plain HolmanError.
Bad JSON or unexpected response shapes also raise plain HolmanError.

Each class defines a ``__repr__`` that surfaces diagnostic attributes
(``status_code``, truncated ``response_body``, ``retry_after_seconds``),
making ``logger.error('request failed: %r', error)`` produce useful output
without the caller having to reconstruct the context manually. The response
body is truncated by :func:`pyholman._strings.format_value_for_repr` to keep
log lines bounded when Holman returns a large HTML error page.
"""

import logging

from pyholman._strings import format_value_for_repr

__all__: list[str] = [
    'HolmanError',
    'RateLimitError',
    'TransientHolmanError',
]

logger: logging.Logger = logging.getLogger(__name__)


class HolmanError(Exception):
    """
    Base exception for all pyholman HTTP errors.

    Catch this to handle every error originating from Holman API interactions.
    For more targeted handling (e.g., retrying transient failures without
    catching permanent ones), catch one of the subclasses instead.

    Attributes:
        status_code: HTTP status code from the response, or None if the
            failure occurred before a response was received (for example,
            a connection error or DNS failure).
        response_body: Raw response body as a string, truncated by the caller
            if needed. None if no response body is available. Useful for
            debugging API errors whose JSON structure does not match
            expected shapes.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        """
        Construct a HolmanError.

        Args:
            message: Human-readable error message. Should describe what
                failed and include enough context to identify the request
                (e.g., the URL or operation name).
            status_code: HTTP status code if a response was received.
                None for pre-response failures.
            response_body: Response body content for debugging, if available.
                Callers should truncate before passing to avoid logging
                very large error responses.
        """
        super().__init__(message)
        self.status_code: int | None = status_code
        self.response_body: str | None = response_body

    def __repr__(self) -> str:
        """
        Return a compact, single-line repr surfacing diagnostic attributes.

        Format: ``ClassName(message='...', status_code=N, response_body=...)``

        The message is the exception's string form (from ``super().args[0]``).
        The response body is rendered via
        :func:`pyholman._strings.format_value_for_repr`, which truncates long
        values so the repr stays bounded even when Holman returns a large
        error page.

        Returns:
            A single-line string suitable for logging with ``%r`` and for
            REPL inspection.
        """
        message: str = str(self)
        formatted_body: str = format_value_for_repr(self.response_body)
        return (
            f'{self.__class__.__name__}('
            f"message='{message}', "
            f'status_code={self.status_code}, '
            f'response_body={formatted_body}'
            f')'
        )


class TransientHolmanError(HolmanError):
    """
    Raised for failures that may succeed on retry.

    Includes:
        - Request timeouts (connect or read)
        - Connection errors (DNS, TCP, TLS)
        - HTTP 5xx server errors
        - HTTP 429 rate limiting (see the RateLimitError subclass)

    The retry decorator in retry.py catches this exception type (and
    therefore also catches RateLimitError, which is a subclass). Non-retryable
    errors (HTTP 4xx other than 429) raise plain HolmanError and propagate
    without retry.

    ``__repr__`` is inherited from ``HolmanError`` — the set of diagnostic
    attributes is the same.
    """


class RateLimitError(TransientHolmanError):
    """
    Raised when Holman's API returns HTTP 429 (rate limited).

    Carries the server's suggested retry delay in seconds, extracted from
    the ``Retry-After`` response header when present. When absent, callers
    should fall back to exponential backoff — the retry module's wait
    strategy handles this automatically.

    Attributes:
        retry_after_seconds: Seconds to wait before retrying, as suggested
            by the server. A value of 0.0 indicates the server did not
            provide guidance; callers should use their default backoff
            strategy in that case.
    """

    def __init__(
        self,
        retry_after_seconds: float,
        response_body: str | None = None,
    ) -> None:
        """
        Construct a RateLimitError.

        Args:
            retry_after_seconds: Server-suggested wait before retry, in
                seconds. Parsed from the Retry-After header; pass 0.0 if
                the header was absent or unparseable.
            response_body: Response body for debugging, if available.
        """
        super().__init__(
            message=f'Rate limit exceeded; retry after {retry_after_seconds:.1f}s',
            status_code=429,
            response_body=response_body,
        )
        self.retry_after_seconds: float = retry_after_seconds

    def __repr__(self) -> str:
        """
        Return a compact repr including the retry-after value.

        Overrides ``HolmanError.__repr__`` to surface
        ``retry_after_seconds`` — the distinguishing attribute for this
        subclass — so it appears in log output without the caller having
        to type-check and access it manually.

        Format:
            ``RateLimitError(retry_after_seconds=N.N, status_code=429,
            response_body=...)``

        The base-class message is redundant with ``retry_after_seconds``
        (the message is derived from it during construction) and is omitted
        to keep the repr tight.

        Returns:
            A single-line string suitable for logging with ``%r``.
        """
        formatted_body: str = format_value_for_repr(self.response_body)
        return (
            f'{self.__class__.__name__}('
            f'retry_after_seconds={self.retry_after_seconds:.1f}, '
            f'status_code={self.status_code}, '
            f'response_body={formatted_body}'
            f')'
        )
