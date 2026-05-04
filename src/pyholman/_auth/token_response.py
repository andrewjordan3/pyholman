# src/pyholman/_auth/token_response.py
"""
Pydantic model for the OAuth2 token-endpoint response.

Shape confirmed against two sources:
    - Holman developer guide, page 6 ("POST /sso/sts/connect/token").
    - Postman collection shipped with the partner onboarding pack,
      request ``Auth > POST .../connect/token``.

Both documents specify four fields on the success response:
``access_token``, ``token_type`` (always ``"Bearer"``), ``expires_in``
(seconds until the token expires, a positive integer), and ``scope``
(space-separated, optional on responses but always present in practice).

pyholman also hardcodes the ``Authorization: Bearer <token>`` scheme
downstream, so accepting a non-Bearer ``token_type`` would quietly
produce a broken header rather than a loud error. The field validator
below rejects anything else — if Holman ever starts issuing MAC or
DPoP tokens, the library needs a deliberate change, not a silent
acceptance.
"""

import logging

from pydantic import Field, field_validator

from pyholman._core.constants import BEARER_SCHEME
from pyholman._core.response import ResponseModel

__all__: list[str] = ['TokenResponse']

logger: logging.Logger = logging.getLogger(__name__)


class TokenResponse(ResponseModel):
    """
    Parsed OAuth2 token-endpoint response.

    Subclasses :class:`ResponseModel` (``extra='ignore'``) so unknown
    fields Holman adds over time — ``issued_at``, ``refresh_token``,
    …  — are dropped silently rather than raising.

    Attributes:
        access_token: The opaque bearer token to carry in the
            ``Authorization`` header on every subsequent API call.
        token_type: The token scheme. Validated to be a case-insensitive
            ``"bearer"``; see the module docstring for the rationale.
        expires_in: Seconds from "now" until the token expires. Must
            be strictly positive — a zero or negative value would
            make the token already-expired at issue, which is a server
            bug pyholman has no way to recover from.
        scope: Space-separated list of scopes the token is authorized
            for, or ``None`` if the server omitted the field. pyholman
            does not inspect scopes today, but the field is captured
            so DEBUG logging surfaces it.
    """

    access_token: str
    token_type: str
    expires_in: int = Field(gt=0)
    scope: str | None = None

    @field_validator('token_type')
    @classmethod
    def _validate_bearer_token_type(cls, value: str) -> str:
        """
        Reject token types other than Bearer.

        OAuth2 (RFC 6749 §5.1) specifies ``token_type`` is
        case-insensitive, so ``'bearer'``, ``'Bearer'``, and
        ``'BEARER'`` are all accepted. Other schemes like ``'MAC'`` or
        ``'DPoP'`` are rejected because the ``Authorization`` header
        construction downstream hardcodes the ``Bearer`` scheme —
        silently accepting a different type would produce a broken
        header at request time, far from the root cause.

        Args:
            value: The raw ``token_type`` string from the response.

        Returns:
            ``value`` unchanged, for use in the validated model.

        Raises:
            ValueError: If ``value`` is not a case-insensitive
                ``"bearer"``.
        """
        if value.lower() != BEARER_SCHEME.lower():
            raise ValueError(
                f'Unsupported token_type {value!r}; only {BEARER_SCHEME} is supported.'
            )
        return value
