# tests/_config/test_retry.py
"""Tests for RetryConfig."""

import pytest
from pydantic import ValidationError

from pyholman._config import RetryConfig

__all__: list[str] = []


_DEFAULT_MAX_ATTEMPTS: int = 5
_DEFAULT_BACKOFF_MAX_SECONDS: float = 60.0


class TestRetryConfigDefaults:
    def test_all_defaults_valid(self) -> None:
        config: RetryConfig = RetryConfig()
        assert config.max_attempts == _DEFAULT_MAX_ATTEMPTS
        assert config.backoff_max_seconds == _DEFAULT_BACKOFF_MAX_SECONDS

    def test_partial_override_preserves_other_default(self) -> None:
        config: RetryConfig = RetryConfig(max_attempts=3)
        assert config.max_attempts == 3
        assert config.backoff_max_seconds == _DEFAULT_BACKOFF_MAX_SECONDS


class TestRetryConfigMaxAttempts:
    @pytest.mark.parametrize('valid_value', [1, 2, 5, 10, 1000])
    def test_accepts_values_at_or_above_one(self, valid_value: int) -> None:
        config: RetryConfig = RetryConfig(max_attempts=valid_value)
        assert config.max_attempts == valid_value

    @pytest.mark.parametrize('invalid_value', [0, -1, -100])
    def test_rejects_values_below_one(self, invalid_value: int) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(max_attempts=invalid_value)

    def test_rejects_non_integer(self) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(max_attempts='five')  # type: ignore[arg-type]


class TestRetryConfigBackoffMaxSeconds:
    @pytest.mark.parametrize('valid_value', [0.001, 1.0, 60.0, 3600.0])
    def test_accepts_strictly_positive_values(self, valid_value: float) -> None:
        config: RetryConfig = RetryConfig(backoff_max_seconds=valid_value)
        assert config.backoff_max_seconds == valid_value

    @pytest.mark.parametrize('invalid_value', [0.0, -0.1, -60.0])
    def test_rejects_zero_or_negative_values(self, invalid_value: float) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(backoff_max_seconds=invalid_value)

    def test_integer_value_is_coerced(self) -> None:
        # Pydantic coerces ints to floats for float-annotated fields.
        config: RetryConfig = RetryConfig(backoff_max_seconds=30)  # type: ignore[arg-type]
        assert config.backoff_max_seconds == 30.0


class TestRetryConfigImmutability:
    def test_is_frozen(self) -> None:
        config: RetryConfig = RetryConfig()
        with pytest.raises(ValidationError):
            config.max_attempts = 10  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            RetryConfig(jitter=0.1)  # type: ignore[call-arg]
