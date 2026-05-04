# tests/_endpoints/contacts/test_filters.py
"""Tests for ContactFilters — last_change_date and the strict guard."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pyholman._endpoints.contacts import ContactFilters

__all__: list[str] = []


class TestDefaultModel:
    def test_no_args_construction(self) -> None:
        filters: ContactFilters = ContactFilters()
        assert filters.last_change_date is None

    def test_empty_dict_validates(self) -> None:
        filters: ContactFilters = ContactFilters.model_validate({})
        assert filters.last_change_date is None


class TestLastChangeDate:
    def test_utc_aware_value_accepted(self) -> None:
        instant: datetime = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)
        filters: ContactFilters = ContactFilters(last_change_date=instant)
        assert filters.last_change_date == instant

    def test_naive_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match='timezone-aware'):
            ContactFilters(
                last_change_date=datetime(2026, 4, 20, 12, 0),  # noqa: DTZ001
            )

    def test_non_utc_value_rejected(self) -> None:
        plus_five: timezone = timezone(timedelta(hours=5))
        with pytest.raises(ValidationError, match='UTC'):
            ContactFilters(
                last_change_date=datetime(2026, 4, 20, 12, 0, tzinfo=plus_five),
            )


class TestExtraForbid:
    @pytest.mark.parametrize(
        'deferred_key',
        [
            'hire_date_code',
            'activation_date_code',
            'deactivation_date_code',
            'termination_date_code',
        ],
    )
    def test_date_code_parameters_rejected(self, deferred_key: str) -> None:
        # All four date-code parameters are deferred for the unified
        # date-code work; until then they must surface as validation
        # errors rather than silently being dropped.
        with pytest.raises(ValidationError):
            ContactFilters.model_validate({deferred_key: 1})

    def test_arbitrary_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContactFilters.model_validate({'some_unknown_key': 'value'})
