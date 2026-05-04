# tests/_auth/test_token_response.py
"""Tests for the TokenResponse Pydantic model."""

import pytest
from pydantic import ValidationError

from pyholman._auth.token_response import TokenResponse

__all__: list[str] = []


def _base_payload() -> dict[str, str | int]:
    """Minimal valid payload; individual tests override one field at a time."""
    return {
        'access_token': 'abc123',
        'token_type': 'Bearer',
        'expires_in': 3600,
    }


# =============================================================================
# Happy path
# =============================================================================


class TestHappyPath:
    def test_parses_complete_payload(self) -> None:
        response: TokenResponse = TokenResponse.model_validate(
            {**_base_payload(), 'scope': 'read write'}
        )
        assert response.access_token == 'abc123'
        assert response.token_type == 'Bearer'
        assert response.expires_in == 3600
        assert response.scope == 'read write'

    def test_missing_scope_defaults_to_none(self) -> None:
        response: TokenResponse = TokenResponse.model_validate(_base_payload())
        assert response.scope is None


# =============================================================================
# Token type validation
# =============================================================================


class TestTokenTypeValidator:
    @pytest.mark.parametrize('token_type', ['bearer', 'Bearer', 'BEARER', 'BeArEr'])
    def test_case_insensitive_bearer_accepted(self, token_type: str) -> None:
        response: TokenResponse = TokenResponse.model_validate(
            {**_base_payload(), 'token_type': token_type}
        )
        # The validator accepts any casing but does not normalize the
        # stored value — downstream code should use the scheme string it
        # hardcodes, not read it back off the model.
        assert response.token_type == token_type

    @pytest.mark.parametrize('token_type', ['MAC', 'DPoP', 'basic', ''])
    def test_non_bearer_token_type_rejected(self, token_type: str) -> None:
        with pytest.raises(ValidationError, match='Unsupported token_type'):
            TokenResponse.model_validate({**_base_payload(), 'token_type': token_type})


# =============================================================================
# expires_in validation
# =============================================================================


class TestExpiresInValidation:
    def test_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TokenResponse.model_validate({**_base_payload(), 'expires_in': 0})

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TokenResponse.model_validate({**_base_payload(), 'expires_in': -1})


# =============================================================================
# Required fields
# =============================================================================


class TestRequiredFields:
    @pytest.mark.parametrize(
        'field_to_drop',
        ['access_token', 'token_type', 'expires_in'],
    )
    def test_missing_required_field_raises(self, field_to_drop: str) -> None:
        payload: dict[str, str | int] = _base_payload()
        del payload[field_to_drop]
        with pytest.raises(ValidationError):
            TokenResponse.model_validate(payload)


# =============================================================================
# extra='ignore'
# =============================================================================


class TestExtraFieldsIgnored:
    def test_unknown_field_silently_dropped(self) -> None:
        # ``ResponseModel`` uses ``extra='ignore'`` so a future Holman
        # response field (``refresh_token``, ``issued_at``, …) does not
        # break parsing today.
        response: TokenResponse = TokenResponse.model_validate(
            {
                **_base_payload(),
                'refresh_token': 'not-modeled-yet',
                'issued_at': '2026-04-22T00:00:00Z',
            }
        )
        assert response.access_token == 'abc123'
        assert not hasattr(response, 'refresh_token')
        assert not hasattr(response, 'issued_at')
