# tests/_config/test_incremental.py
"""Tests for IncrementalConfig."""

from datetime import date

import pytest
from pydantic import ValidationError

from pyholman._config import IncrementalConfig

__all__: list[str] = []


class TestIncrementalConfig:
    def test_default_construction_yields_documented_defaults(self) -> None:
        config: IncrementalConfig = IncrementalConfig()
        assert config.lookback_days == 7
        assert config.earliest_date is None

    def test_explicit_lookback_days_preserved(self) -> None:
        config: IncrementalConfig = IncrementalConfig(lookback_days=14)
        assert config.lookback_days == 14
        assert config.earliest_date is None

    def test_valid_construction_with_earliest_date(self) -> None:
        floor: date = date(2020, 1, 1)
        config: IncrementalConfig = IncrementalConfig(
            lookback_days=30,
            earliest_date=floor,
        )
        assert config.lookback_days == 30
        assert config.earliest_date == floor

    @pytest.mark.parametrize('lookback_days', [0, -1])
    def test_non_positive_lookback_days_rejected(
        self,
        lookback_days: int,
    ) -> None:
        with pytest.raises(ValidationError):
            IncrementalConfig(lookback_days=lookback_days)

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            IncrementalConfig(
                oops='typo',  # type: ignore[call-arg]
            )

    def test_is_frozen(self) -> None:
        config: IncrementalConfig = IncrementalConfig()
        with pytest.raises(ValidationError):
            config.lookback_days = 14  # type: ignore[misc]
