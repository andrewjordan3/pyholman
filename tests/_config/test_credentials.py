# tests/_config/test_credentials.py
"""Tests for CredentialsConfig."""

import pytest
from pydantic import SecretStr, ValidationError

from pyholman._config import CredentialsConfig

__all__: list[str] = []


class TestCredentialsConfig:
    def test_valid_construction(self) -> None:
        credentials: CredentialsConfig = CredentialsConfig(
            client_id='cust-api.org-XXXX.user-abc',
            client_secret='real-secret',
        )
        assert credentials.client_id == 'cust-api.org-XXXX.user-abc'
        assert isinstance(credentials.client_secret, SecretStr)
        assert credentials.client_secret.get_secret_value() == 'real-secret'

    def test_secret_not_shown_in_repr(self) -> None:
        credentials: CredentialsConfig = CredentialsConfig(
            client_id='cid',
            client_secret='super-secret',
        )
        assert 'super-secret' not in repr(credentials)

    def test_is_frozen(self) -> None:
        credentials: CredentialsConfig = CredentialsConfig(
            client_id='cid',
            client_secret='s',
        )
        with pytest.raises(ValidationError):
            credentials.client_id = 'changed'  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            CredentialsConfig(
                client_id='cid',
                client_secret='s',
                oops='typo',  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize(
        'missing_field',
        ['client_id', 'client_secret'],
    )
    def test_missing_required_field_rejected(self, missing_field: str) -> None:
        fields: dict[str, str] = {
            'client_id': 'cid',
            'client_secret': 'sec',
        }
        del fields[missing_field]
        with pytest.raises(ValidationError, match=missing_field):
            CredentialsConfig(**fields)  # type: ignore[arg-type]
