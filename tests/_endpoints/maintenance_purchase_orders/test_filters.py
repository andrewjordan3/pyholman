# tests/_endpoints/maintenance_purchase_orders/test_filters.py
"""Tests for MaintenancePurchaseOrderFilters validation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderFilters,
)

__all__: list[str] = []


class TestLastChangeDateValidation:
    def test_default_none_accepted(self) -> None:
        filters: MaintenancePurchaseOrderFilters = MaintenancePurchaseOrderFilters()
        assert filters.last_change_date is None

    def test_explicit_none_accepted(self) -> None:
        filters: MaintenancePurchaseOrderFilters = MaintenancePurchaseOrderFilters(
            last_change_date=None
        )
        assert filters.last_change_date is None

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match='timezone-aware'):
            MaintenancePurchaseOrderFilters(
                last_change_date=datetime(2026, 4, 20, 0, 0, 0),  # noqa: DTZ001
            )

    def test_non_utc_datetime_rejected(self) -> None:
        eastern: timezone = timezone(timedelta(hours=-5))
        with pytest.raises(ValidationError, match='UTC'):
            MaintenancePurchaseOrderFilters(
                last_change_date=datetime(2026, 4, 20, 0, 0, 0, tzinfo=eastern),
            )

    def test_utc_datetime_accepted(self) -> None:
        value: datetime = datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC)
        filters: MaintenancePurchaseOrderFilters = MaintenancePurchaseOrderFilters(
            last_change_date=value
        )
        assert filters.last_change_date == value

    def test_z_suffixed_iso_string_parses_to_utc_aware(self) -> None:
        filters: MaintenancePurchaseOrderFilters = (
            MaintenancePurchaseOrderFilters.model_validate(
                {'last_change_date': '2026-04-20T14:30:45Z'}
            )
        )
        assert filters.last_change_date == datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC)
        assert filters.last_change_date is not None
        assert filters.last_change_date.utcoffset() == timedelta(0)


class TestExtraForbid:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MaintenancePurchaseOrderFilters.model_validate({'unknown_filter': 'x'})

    def test_status_codes_not_accepted(self) -> None:
        # status_codes belongs to vehicles, not maintenance POs. Confirm
        # the strict schema rejects it rather than silently dropping.
        with pytest.raises(ValidationError):
            MaintenancePurchaseOrderFilters.model_validate({'status_codes': [1]})
