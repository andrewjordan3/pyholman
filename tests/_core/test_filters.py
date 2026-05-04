# tests/_core/test_filters.py
"""Tests for ``IncrementalFilters`` base class."""

from datetime import UTC, datetime

import pytest

from pyholman._core import IncrementalFilters
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderFilters,
)

__all__: list[str] = []


class _ConcreteFilters(IncrementalFilters):
    other_field: int | None = None


class TestSubclassEnforcement:
    def test_concrete_subclass_inherits_classvar(self) -> None:
        # The base class supplies ``WATERMARK_FIELD_NAME`` and
        # ``last_change_date``; subclasses inherit both without
        # redeclaring.
        instance: _ConcreteFilters = _ConcreteFilters()
        assert instance.last_change_date is None
        assert instance.WATERMARK_FIELD_NAME == 'last_change_date'


class TestWithWindowStart:
    def test_returns_new_instance(self) -> None:
        original: _ConcreteFilters = _ConcreteFilters(other_field=42)
        anchor: datetime = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)

        updated: _ConcreteFilters = original.with_window_start(anchor)

        assert updated is not original

    def test_watermark_field_set_to_window_start(self) -> None:
        original: _ConcreteFilters = _ConcreteFilters()
        anchor: datetime = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)

        updated: _ConcreteFilters = original.with_window_start(anchor)

        assert updated.last_change_date == anchor

    def test_other_fields_preserved(self) -> None:
        original: _ConcreteFilters = _ConcreteFilters(other_field=42)
        anchor: datetime = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)

        updated: _ConcreteFilters = original.with_window_start(anchor)

        assert updated.other_field == 42

    def test_round_trips_through_model_validate(self) -> None:
        # ``model_validate`` is the path taken by ``with_window_start``;
        # the cleanest witness is to construct a subclass whose validator
        # transforms the watermark value, then confirm the override
        # passes through it. We piggyback on the real
        # ``MaintenancePurchaseOrderFilters`` validator (rejects naive
        # datetimes) to assert the validator runs on the override path.
        filters: MaintenancePurchaseOrderFilters = MaintenancePurchaseOrderFilters()
        naive: datetime = datetime(2026, 4, 20, 12, 0)  # noqa: DTZ001 — intentional.
        with pytest.raises(ValueError, match='timezone-aware'):
            filters.with_window_start(naive)
