# tests/_endpoints/engine_hours/test_filters.py
"""Tests for EngineHoursFilters — the empty filter model and its strict guard."""

import pytest
from pydantic import ValidationError

from pyholman._endpoints.engine_hours import EngineHoursFilters

__all__: list[str] = []


class TestEmptyModel:
    def test_no_args_construction(self) -> None:
        filters: EngineHoursFilters = EngineHoursFilters()
        assert filters.model_dump() == {}

    def test_empty_dict_validates(self) -> None:
        assert EngineHoursFilters.model_validate({}).model_dump() == {}


class TestExtraForbid:
    def test_last_change_date_rejected(self) -> None:
        # Deliberately omitted pending verification that Holman does not
        # hang on the parameter the way the odometer endpoint does.
        with pytest.raises(ValidationError):
            EngineHoursFilters.model_validate(
                {'last_change_date': '2026-04-20T00:00:00Z'}
            )

    def test_hourmeter_hist_date_code_rejected(self) -> None:
        # Deferred for the unified date-code work.
        with pytest.raises(ValidationError):
            EngineHoursFilters.model_validate({'hourmeter_hist_date_code': 1})

    def test_arbitrary_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EngineHoursFilters.model_validate({'some_unknown_key': 'value'})
