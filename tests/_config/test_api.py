# tests/_config/test_api.py
"""Tests for ApiConfig."""

import pytest
from pydantic import ValidationError

from pyholman._config import ApiConfig

__all__: list[str] = []


_DEFAULT_PAGE_SIZE: int = 200
_PRODUCTION_BASE_URL: str = 'https://api.holman.solutions/'


class TestApiConfigBaseUrl:
    def test_default_base_url_is_production(self) -> None:
        # Production is the default so the common-case ``ApiConfig()`` is
        # no-arg constructible. ``HttpUrl`` normalizes to include a
        # trailing slash, so the stringified default carries one whether
        # or not the source literal does.
        api: ApiConfig = ApiConfig()
        assert str(api.base_url) == _PRODUCTION_BASE_URL

    def test_accepts_valid_https_url(self) -> None:
        api: ApiConfig = ApiConfig(base_url='https://api.holman.solutions')
        # HttpUrl normalizes to include a trailing slash; stringify for
        # portable comparison across pydantic minor versions.
        assert str(api.base_url).startswith('https://api.holman.solutions')

    def test_accepts_http_url(self) -> None:
        api: ApiConfig = ApiConfig(base_url='http://localhost:8000')
        assert str(api.base_url).startswith('http://localhost')

    @pytest.mark.parametrize(
        'bad_url',
        [
            'not-a-url',
            'ftp://example.com',
            '',
            'https://',
        ],
    )
    def test_rejects_invalid_urls(self, bad_url: str) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(base_url=bad_url)


class TestApiConfigPageSize:
    def test_default_is_holman_documented_value(self) -> None:
        api: ApiConfig = ApiConfig()
        assert api.page_size == _DEFAULT_PAGE_SIZE

    @pytest.mark.parametrize('valid_value', [1, 50, 200, 500, 1000])
    def test_accepts_values_inside_bounds(self, valid_value: int) -> None:
        api: ApiConfig = ApiConfig(page_size=valid_value)
        assert api.page_size == valid_value

    @pytest.mark.parametrize('invalid_value', [0, -1, 1001, 5000])
    def test_rejects_values_outside_bounds(self, invalid_value: int) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(page_size=invalid_value)

    def test_rejects_non_integer(self) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(
                page_size='two hundred',  # type: ignore[arg-type]
            )


class TestApiConfigUseTruststore:
    def test_default_is_false(self) -> None:
        api: ApiConfig = ApiConfig()
        assert api.use_truststore is False

    @pytest.mark.parametrize('valid_value', [True, False])
    def test_accepts_bools(self, valid_value: bool) -> None:
        api: ApiConfig = ApiConfig(use_truststore=valid_value)
        assert api.use_truststore is valid_value

    def test_rejects_non_bool_string(self) -> None:
        # FrozenModel is strict; random strings do not coerce to bool.
        with pytest.raises(ValidationError):
            ApiConfig(
                use_truststore='not-a-bool',  # type: ignore[arg-type]
            )


class TestApiConfigModelBehavior:
    def test_is_frozen(self) -> None:
        api: ApiConfig = ApiConfig()
        with pytest.raises(ValidationError):
            api.base_url = 'https://other.example.com'  # type: ignore[assignment]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            ApiConfig(
                timeout=30,  # type: ignore[call-arg]
            )
