# tests/_config/test_resources.py
"""Tests for the discriminated ResourceConfig union."""

import pytest
from pydantic import TypeAdapter, ValidationError

from pyholman._config import (
    ContactsResourceConfig,
    EngineHoursResourceConfig,
    MaintenancePurchaseOrdersResourceConfig,
    OdometerResourceConfig,
    ResourceConfig,
    VehiclesResourceConfig,
)
from pyholman._endpoints.contacts import ContactFilters
from pyholman._endpoints.engine_hours import EngineHoursFilters
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderFilters,
)
from pyholman._endpoints.odometer import OdometerFilters
from pyholman._endpoints.vehicles import VehiclesFilters

__all__: list[str] = []


_adapter: TypeAdapter[ResourceConfig] = TypeAdapter(ResourceConfig)


class TestVehiclesVariant:
    def test_minimum_entry_defaults(self) -> None:
        result = _adapter.validate_python({'name': 'vehicles'})
        assert isinstance(result, VehiclesResourceConfig)
        assert result.incremental is False
        assert isinstance(result.filters, VehiclesFilters)
        assert result.filters.status_codes is None

    def test_full_entry_round_trip(self) -> None:
        result = _adapter.validate_python(
            {
                'name': 'vehicles',
                'incremental': True,
                'filters': {'status_codes': [1]},
            }
        )
        assert isinstance(result, VehiclesResourceConfig)
        assert result.incremental is True
        assert result.filters.status_codes == (1,)

    def test_invalid_status_code_rejected_at_config_load(self) -> None:
        with pytest.raises(ValidationError):
            _adapter.validate_python(
                {'name': 'vehicles', 'filters': {'status_codes': [99]}}
            )

    def test_unknown_filter_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _adapter.validate_python(
                {'name': 'vehicles', 'filters': {'unknown_key': 1}}
            )


class TestMaintenancePurchaseOrdersVariant:
    def test_minimum_entry_defaults(self) -> None:
        result = _adapter.validate_python({'name': 'maintenance_purchase_orders'})
        assert isinstance(result, MaintenancePurchaseOrdersResourceConfig)
        assert result.incremental is False
        assert isinstance(result.filters, MaintenancePurchaseOrderFilters)


class TestContactsVariant:
    def test_minimum_entry_defaults(self) -> None:
        result = _adapter.validate_python({'name': 'contacts'})
        assert isinstance(result, ContactsResourceConfig)
        assert result.incremental is False
        assert isinstance(result.filters, ContactFilters)


class TestOdometerVariant:
    def test_minimum_entry_defaults(self) -> None:
        result = _adapter.validate_python({'name': 'odometer'})
        assert isinstance(result, OdometerResourceConfig)
        assert result.incremental is False
        assert isinstance(result.filters, OdometerFilters)

    def test_incremental_true_rejected(self) -> None:
        with pytest.raises(ValidationError, match='odometer'):
            _adapter.validate_python({'name': 'odometer', 'incremental': True})


class TestEngineHoursVariant:
    def test_minimum_entry_defaults(self) -> None:
        result = _adapter.validate_python({'name': 'engine_hours'})
        assert isinstance(result, EngineHoursResourceConfig)
        assert result.incremental is False
        assert isinstance(result.filters, EngineHoursFilters)

    def test_incremental_true_rejected(self) -> None:
        with pytest.raises(ValidationError, match='engine_hours'):
            _adapter.validate_python({'name': 'engine_hours', 'incremental': True})


class TestDiscriminator:
    def test_unknown_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _adapter.validate_python({'name': 'bogus'})

    def test_missing_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _adapter.validate_python({})
