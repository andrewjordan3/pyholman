# src/pyholman/_transport/request.py
"""
One-shot send-and-validate helper used by every pyholman API caller.

:func:`send_request` is the single function callers reach for when they
have a built ``httpx.Request`` and want a validated ``httpx.Response``
back. It ties together three internal concerns so each caller does
not repeat them:

    1. Connection-level failures (``httpx.RequestError`` and any
       subclass) are translated to :class:`TransientHolmanError` via
       :func:`translate_httpx_request_error` and raised with the
       original httpx exception chained through ``__cause__``.
    2. Response status is validated by :func:`raise_for_holman_status`,
       which raises the appropriate pyholman exception for non-2xx
       responses (``RateLimitError`` for 429, ``HolmanError`` for other
       client and unexpected statuses, ``TransientHolmanError`` for
       server errors).
    3. Retry policy from ``transport.retry_config`` is applied around
       the whole thing via :func:`with_retry`, so
       ``TransientHolmanError`` and ``RateLimitError`` trigger a retry
       without the caller having to wire one up.

Callers (:class:`TokenManager`, ``HolmanClient``) construct a single
:class:`HttpTransport` once and pass it to every call. They do not
touch the retry helper directly; retry is an implementation detail of
this helper.
"""

import logging
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ValidationError

from pyholman._transport.exceptions import HolmanError
from pyholman._transport.retry import with_retry
from pyholman._transport.status import (
    raise_for_holman_status,
    translate_httpx_request_error,
)
from pyholman._transport.transport import HttpTransport

__all__: list[str] = ['parse_response_body', 'send_request']

logger: logging.Logger = logging.getLogger(__name__)


def send_request(
    transport: HttpTransport,
    request: httpx.Request,
) -> httpx.Response:
    """
    Send ``request`` through ``transport`` with retry, error translation,
    and status validation.

    On a retryable failure (network error, 5xx, 429) the call is
    repeated per ``transport.retry_config``. Non-retryable failures
    (4xx other than 429, unexpected 1xx/3xx) raise :class:`HolmanError`
    immediately.

    Args:
        transport: Bundle of the ``httpx.Client`` to send through and
            the retry policy to apply. Constructed once per run via
            :func:`pyholman._transport.build_transport` and shared
            across callers.
        request: The fully-built ``httpx.Request``. Authentication
            headers (if any) must already be attached; this helper does
            not add them.

    Returns:
        The ``httpx.Response`` for any 2xx status, body fully received.

    Raises:
        TransientHolmanError: For connection-level failures and 5xx
            responses after retries are exhausted. Chained via
            ``__cause__`` when the underlying cause was an
            ``httpx.RequestError``.
        RateLimitError: For 429 responses after retries are exhausted.
        HolmanError: For 4xx (other than 429) and unexpected status
            classes (1xx, 3xx). These are not retried.
    """

    def _send_once() -> httpx.Response:
        try:
            response: httpx.Response = transport.client.send(request)
        except httpx.RequestError as http_error:
            raise translate_httpx_request_error(http_error) from http_error
        raise_for_holman_status(response, clock=transport.clock)
        return response

    wrapped_send: Callable[[], httpx.Response] = with_retry(
        transport.retry_config, _send_once
    )
    return wrapped_send()


def parse_response_body[TModel: BaseModel](
    response: httpx.Response,
    response_model: type[TModel],
    endpoint_description: str,
) -> TModel:
    """
    Validate ``response.content`` against ``response_model``, wrapping
    failures as :class:`HolmanError`.

    Every pyholman caller that turns a validated HTTP response into a
    typed Pydantic model needs the same glue: feed the raw bytes to
    ``model_validate_json``, catch ``ValidationError``, and raise a
    :class:`HolmanError` carrying the status code and response body so
    the caller has diagnostic context. The helper factors that glue so
    :class:`TokenManager` and :class:`HolmanClient` do not repeat it.

    The generic bound is :class:`pydantic.BaseModel` rather than
    pyholman's ``ResponseModel`` so callers can also pass
    parameterized envelopes like ``PaginatedResponse[VehicleResponse]``
    — Pydantic's class-getitem returns a concrete ``BaseModel``
    subclass that is not statically a ``ResponseModel``. Bounding on
    ``BaseModel`` keeps the helper usable for every model pyholman
    constructs.

    Type parameters:
        TModel: The concrete Pydantic model to validate against.
            Return type matches so callers do not need to cast.

    Args:
        response: The ``httpx.Response`` whose body is being parsed.
            Already received in full by ``send_request``; this helper
            does not stream.
        response_model: The Pydantic model class used for validation.
        endpoint_description: A short human-readable label for the
            endpoint (e.g. ``'the auth endpoint'`` or
            ``'/vehicles/basic-query'``). Appears in the error message
            so log output and exception reprs identify where the
            failure came from without the caller having to compose
            the string itself.

    Returns:
        The validated ``response_model`` instance.

    Raises:
        HolmanError: If ``response.content`` does not satisfy
            ``response_model``. The original
            :class:`pydantic.ValidationError` is chained via
            ``__cause__`` so the root cause is preserved, and the
            error carries ``status_code`` and ``response_body`` from
            the response for diagnostics.
    """
    try:
        return response_model.model_validate_json(response.content)
    except ValidationError as validation_error:
        raise HolmanError(
            message=(
                f'Holman returned unexpected response shape for {endpoint_description}.'
            ),
            status_code=response.status_code,
            response_body=response.text,
        ) from validation_error
