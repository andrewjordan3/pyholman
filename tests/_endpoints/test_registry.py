# tests/_endpoints/test_registry.py
"""Tests for the resource registry."""

import pytest
from pydantic import ValidationError

from pyholman._core import ResponseModel
from pyholman._endpoints.contacts import Contact, ContactQuery
from pyholman._endpoints.engine_hours import EngineHours, EngineHoursQuery
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrder,
    MaintenancePurchaseOrderQuery,
)
from pyholman._endpoints.odometer import Odometer, OdometerQuery
from pyholman._endpoints.registry import (
    ENDPOINT_NAMES,
    REGISTRY,
    ResourceRegistryEntry,
    get_registry_entry,
)
from pyholman._endpoints.vehicles import Vehicle, VehiclesQuery

__all__: list[str] = []


_EXPECTED_RESOURCE_NAMES: frozenset[str] = frozenset(
    {
        'vehicles',
        'maintenance_purchase_orders',
        'contacts',
        'odometer',
        'engine_hours',
    }
)


class TestRegistryShape:
    def test_registry_has_all_five_resources(self) -> None:
        assert set(REGISTRY) == _EXPECTED_RESOURCE_NAMES

    def test_endpoint_names_matches_expected_set(self) -> None:
        # Cross-check: ``ENDPOINT_NAMES`` is derived from ``EndpointName``
        # (the Literal). This test catches drift between the Literal and
        # the registry entries — adding a registry entry without
        # extending the Literal fails here.
        assert frozenset(ENDPOINT_NAMES) == _EXPECTED_RESOURCE_NAMES

    def test_entry_name_matches_key(self) -> None:
        for resource_name, entry in REGISTRY.items():
            assert entry.name == resource_name

    def test_registry_is_immutable(self) -> None:
        with pytest.raises(TypeError):
            REGISTRY['vehicles'] = None  # type: ignore[index]


class TestRegistryEntriesContent:
    def test_vehicles_entry(self) -> None:
        entry: ResourceRegistryEntry = REGISTRY['vehicles']
        assert entry.query_class is VehiclesQuery
        assert entry.response_class is Vehicle
        assert entry.supports_incremental is True

    def test_maintenance_purchase_orders_entry(self) -> None:
        entry: ResourceRegistryEntry = REGISTRY['maintenance_purchase_orders']
        assert entry.query_class is MaintenancePurchaseOrderQuery
        assert entry.response_class is MaintenancePurchaseOrder
        assert entry.supports_incremental is True

    def test_contacts_entry(self) -> None:
        entry: ResourceRegistryEntry = REGISTRY['contacts']
        assert entry.query_class is ContactQuery
        assert entry.response_class is Contact
        assert entry.supports_incremental is True

    def test_odometer_entry(self) -> None:
        entry: ResourceRegistryEntry = REGISTRY['odometer']
        assert entry.query_class is OdometerQuery
        assert entry.response_class is Odometer
        assert entry.supports_incremental is False

    def test_engine_hours_entry(self) -> None:
        entry: ResourceRegistryEntry = REGISTRY['engine_hours']
        assert entry.query_class is EngineHoursQuery
        assert entry.response_class is EngineHours
        assert entry.supports_incremental is False

    def test_output_directory_name_attribute_removed(self) -> None:
        # Regression guard: the directory-name field was dropped in favor
        # of using ``entry.name`` directly. Re-introducing the field
        # would create drift between two sources of truth for the same
        # string.
        entry: ResourceRegistryEntry = REGISTRY['vehicles']
        assert not hasattr(entry, 'output_directory_name')


class TestGetRegistryEntry:
    def test_known_resource_returns_entry(self) -> None:
        entry: ResourceRegistryEntry = get_registry_entry('vehicles')
        assert entry is REGISTRY['vehicles']

    def test_unknown_resource_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match='nonexistent'):
            get_registry_entry('nonexistent')

    def test_unknown_resource_error_lists_known_names(self) -> None:
        with pytest.raises(ValueError, match='bogus') as caught:
            get_registry_entry('bogus')
        message: str = str(caught.value)
        for known in _EXPECTED_RESOURCE_NAMES:
            assert known in message


class TestWatermarkInvariants:
    # Use a real ``EndpointName`` literal for ``name`` so the watermark
    # invariant validator (mode='after') is the assertion under test —
    # the ``name`` field is now narrowed to ``EndpointName`` and would
    # otherwise reject a stand-in like ``'bogus'`` first.
    def test_incremental_requires_watermark(self) -> None:
        class _SnapshotResponse(ResponseModel):
            pass

        assert _SnapshotResponse.watermark_column is None

        with pytest.raises(ValidationError, match='watermark_column'):
            ResourceRegistryEntry(
                name='odometer',
                query_class=VehiclesQuery,
                response_class=_SnapshotResponse,
                supports_incremental=True,
            )

    def test_non_incremental_rejects_watermark(self) -> None:
        # ``Vehicle`` has ``watermark_column='last_change_date'``; using it
        # on a non-incremental entry should fail the invariant check.
        with pytest.raises(ValidationError, match='watermark_column'):
            ResourceRegistryEntry(
                name='odometer',
                query_class=VehiclesQuery,
                response_class=Vehicle,
                supports_incremental=False,
            )

    def test_invalid_endpoint_name_rejected(self) -> None:
        # Regression guard for the EndpointName narrowing: any string
        # that is not one of the registered names must fail validation
        # before any other field-level check runs.
        with pytest.raises(ValidationError):
            ResourceRegistryEntry(
                name='bogus',  # type: ignore[arg-type]
                query_class=VehiclesQuery,
                response_class=Vehicle,
                supports_incremental=True,
            )
