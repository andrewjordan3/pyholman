# tests/_endpoints/odometer/test_filters.py
"""Tests for OdometerFilters — the empty filter model and its strict guard."""

import pytest
from pydantic import ValidationError

from pyholman._endpoints.odometer import OdometerFilters

__all__: list[str] = []


class TestEmptyModel:
    def test_no_args_construction(self) -> None:
        filters: OdometerFilters = OdometerFilters()
        assert filters.model_dump() == {}

    def test_empty_dict_validates(self) -> None:
        assert OdometerFilters.model_validate({}).model_dump() == {}


class TestExtraForbid:
    def test_last_change_date_rejected(self) -> None:
        # Explicitly forbidden: Holman's odometer endpoint silently hangs
        # on this parameter, so the filter layer refuses to let users
        # reach that behavior through YAML.
        with pytest.raises(ValidationError):
            OdometerFilters.model_validate({'last_change_date': '2026-04-20T00:00:00Z'})

    def test_odometer_history_date_code_rejected(self) -> None:
        # Deferred for the unified date-code work; until then, surfacing
        # a validation error is preferable to silently dropping the key.
        with pytest.raises(ValidationError):
            OdometerFilters.model_validate({'odometer_history_date_code': 5})

    def test_arbitrary_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OdometerFilters.model_validate({'some_unknown_key': 'value'})
