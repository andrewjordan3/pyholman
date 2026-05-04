# tests/_endpoints/vehicles/test_filters.py
"""Tests for VehiclesFilters validation and computed sold_date_code."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pyholman._endpoints.vehicles import VehiclesFilters

__all__: list[str] = []


class TestSoldDateCodeDerivation:
    def test_no_status_codes_yields_none(self) -> None:
        filters: VehiclesFilters = VehiclesFilters()
        assert filters.sold_date_code is None

    def test_status_codes_without_sold_yields_none(self) -> None:
        filters: VehiclesFilters = VehiclesFilters(status_codes=(0, 1, 2))
        assert filters.sold_date_code is None

    def test_sold_only_yields_5(self) -> None:
        filters: VehiclesFilters = VehiclesFilters(status_codes=(3,))
        assert filters.sold_date_code == 5

    def test_mixed_with_sold_yields_5(self) -> None:
        filters: VehiclesFilters = VehiclesFilters(status_codes=(0, 1, 2, 3))
        assert filters.sold_date_code == 5

    def test_sold_date_code_appears_in_model_dump(self) -> None:
        # Computed fields are serialized by Pydantic's model_dump, which
        # keeps the value discoverable to downstream code without making
        # it an input.
        filters: VehiclesFilters = VehiclesFilters(status_codes=(3,))
        assert filters.model_dump()['sold_date_code'] == 5


class TestStatusCodesValidation:
    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValidationError) as caught:
            VehiclesFilters(status_codes=(7,))
        assert '7' in str(caught.value)

    def test_mixed_valid_and_invalid_rejected_and_names_invalid(self) -> None:
        with pytest.raises(ValidationError) as caught:
            VehiclesFilters(status_codes=(1, 99, 3, -1))
        message: str = str(caught.value)
        assert '99' in message
        assert '-1' in message

    @pytest.mark.parametrize('code', [0, 1, 2, 3])
    def test_each_valid_code_accepted(self, code: int) -> None:
        filters: VehiclesFilters = VehiclesFilters(status_codes=(code,))
        assert filters.status_codes == (code,)


class TestLastChangeDateValidation:
    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match='timezone-aware'):
            VehiclesFilters(
                last_change_date=datetime(2026, 4, 20, 0, 0, 0),  # noqa: DTZ001
            )

    def test_non_utc_datetime_rejected(self) -> None:
        eastern: timezone = timezone(timedelta(hours=-5))
        with pytest.raises(ValidationError, match='UTC'):
            VehiclesFilters(
                last_change_date=datetime(2026, 4, 20, 0, 0, 0, tzinfo=eastern),
            )

    def test_utc_datetime_accepted(self) -> None:
        value: datetime = datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC)
        filters: VehiclesFilters = VehiclesFilters(last_change_date=value)
        assert filters.last_change_date == value

    def test_z_suffixed_iso_string_parses_to_utc_aware(self) -> None:
        filters: VehiclesFilters = VehiclesFilters.model_validate(
            {'last_change_date': '2026-04-20T14:30:45Z'}
        )
        assert filters.last_change_date == datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC)
        assert filters.last_change_date is not None
        assert filters.last_change_date.tzinfo is not None
        assert filters.last_change_date.utcoffset() == timedelta(0)


class TestExtraForbid:
    def test_sold_date_code_is_not_accepted_as_input(self) -> None:
        with pytest.raises(ValidationError):
            VehiclesFilters.model_validate(
                {'status_codes': [3], 'sold_date_code': 9},
            )

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VehiclesFilters.model_validate({'unknown_field': 'x'})
