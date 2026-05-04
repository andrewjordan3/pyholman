# tests/_endpoints/test_query_builder.py
"""Tests for ``build_query_from_filters``."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic import HttpUrl

from pyholman._config import ApiConfig, FleetConfig
from pyholman._core import FrozenModel, QueryInputBase, ResponseModel
from pyholman._endpoints.contacts import ContactQuery
from pyholman._endpoints.engine_hours import EngineHoursQuery
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderQuery,
)
from pyholman._endpoints.odometer import (
    Odometer,
    OdometerFilters,
    OdometerQuery,
)
from pyholman._endpoints.query_builder import build_query_from_filters
from pyholman._endpoints.registry import (
    ResourceRegistryEntry,
    get_registry_entry,
)
from pyholman._endpoints.vehicles import VehiclesFilters, VehiclesQuery

__all__: list[str] = []


_BASE_URL: str = 'https://api.example.test'
_LESSEE_CODES: tuple[str, ...] = ('ABCD', 'EFGH')


@pytest.fixture
def api_config() -> ApiConfig:
    return ApiConfig(base_url=HttpUrl(_BASE_URL))


@pytest.fixture
def fleet_config() -> FleetConfig:
    return FleetConfig(lessee_codes=_LESSEE_CODES)


# =============================================================================
# Populated VehiclesFilters → VehiclesQuery
# =============================================================================


class TestVehicles:
    def test_populated_filters_produce_matching_query(
        self,
        api_config: ApiConfig,
        fleet_config: FleetConfig,
    ) -> None:
        filters: VehiclesFilters = VehiclesFilters(
            status_codes=(1, 3),
            last_change_date=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )

        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=get_registry_entry('vehicles'),
            filters=filters,
            api_config=api_config,
            fleet_config=fleet_config,
        )

        assert isinstance(query, VehiclesQuery)
        assert query.base_url == _BASE_URL + '/'
        assert query.lessee_codes == _LESSEE_CODES
        assert query.status_codes == (1, 3)
        assert query.last_change_date == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        # VehiclesFilters computes ``sold_date_code`` when status_codes
        # contains 3; the computed value flows through ``model_dump``.
        assert query.sold_date_code == 5


# =============================================================================
# Empty OdometerFilters → OdometerQuery
# =============================================================================


class TestOdometer:
    def test_empty_filters_populate_only_inherited_fields(
        self,
        api_config: ApiConfig,
        fleet_config: FleetConfig,
    ) -> None:
        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=get_registry_entry('odometer'),
            filters=OdometerFilters(),
            api_config=api_config,
            fleet_config=fleet_config,
        )

        assert isinstance(query, OdometerQuery)
        # Inherited fields carry the caller-supplied values.
        assert query.base_url == _BASE_URL + '/'
        assert query.lessee_codes == _LESSEE_CODES
        # Inherited cursor fields default to None — OdometerFilters
        # declares no fields, so the dump is ``{}`` and nothing overrides
        # the dataclass defaults.
        assert query.last_change_record_id is None
        assert query.last_change_date is None


# =============================================================================
# filters=None — fetch's no-filter path
# =============================================================================


class TestNoneFilters:
    """
    ``filters=None`` is the explicit "no filter overrides" signal used
    by the public ``fetch`` entry point. The dump short-circuits to
    ``{}`` and every endpoint-specific filter field on the returned
    query falls back to its dataclass default of ``None``.
    """

    @pytest.mark.parametrize(
        ('endpoint_name', 'expected_query_class'),
        [
            ('vehicles', VehiclesQuery),
            ('maintenance_purchase_orders', MaintenancePurchaseOrderQuery),
            ('contacts', ContactQuery),
            ('odometer', OdometerQuery),
            ('engine_hours', EngineHoursQuery),
        ],
    )
    def test_none_filters_produce_no_filter_query(
        self,
        api_config: ApiConfig,
        fleet_config: FleetConfig,
        endpoint_name: str,
        expected_query_class: type[QueryInputBase[ResponseModel]],
    ) -> None:
        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=get_registry_entry(endpoint_name),
            filters=None,
            api_config=api_config,
            fleet_config=fleet_config,
        )

        assert isinstance(query, expected_query_class)
        assert query.base_url == _BASE_URL + '/'
        assert query.lessee_codes == _LESSEE_CODES
        # Inherited cursor fields default to None — no filter dump means
        # nothing overrides them.
        assert query.last_change_record_id is None
        assert query.last_change_date is None

    def test_vehicles_endpoint_specific_fields_default_to_none(
        self,
        api_config: ApiConfig,
        fleet_config: FleetConfig,
    ) -> None:
        # Vehicles is the only endpoint with extra filter fields beyond
        # the inherited cursor fields; assert them explicitly so
        # ``filters=None`` provably means "no overrides anywhere."
        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=get_registry_entry('vehicles'),
            filters=None,
            api_config=api_config,
            fleet_config=fleet_config,
        )
        assert isinstance(query, VehiclesQuery)
        assert query.status_codes is None
        assert query.sold_date_code is None


# =============================================================================
# Frozenness
# =============================================================================


class TestFrozen:
    def test_returned_query_is_frozen(
        self,
        api_config: ApiConfig,
        fleet_config: FleetConfig,
    ) -> None:
        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=get_registry_entry('odometer'),
            filters=OdometerFilters(),
            api_config=api_config,
            fleet_config=fleet_config,
        )

        with pytest.raises(FrozenInstanceError):
            # Attempting to mutate any field on a frozen dataclass must
            # raise; ``lessee_codes`` is a stable inherited field on
            # every endpoint.
            query.lessee_codes = ('ZZZZ',)  # type: ignore[misc]


# =============================================================================
# Isolation — only the three expected inputs flow through
# =============================================================================


class _StubFilters(FrozenModel):
    """Filter model with a single field matching ``_StubQuery.widget``."""

    widget: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _StubQuery(QueryInputBase[Odometer]):
    """Minimal QueryInputBase subclass for isolation testing."""

    endpoint_path: ClassVar[str] = '/CustomerDataAPI/stub/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = Odometer

    widget: str = ''


class TestIsolation:
    def test_only_expected_inputs_flow_through(self) -> None:
        # Build a stub registry entry whose ``query_class`` is the test-
        # local ``_StubQuery``. Pair it with ``Odometer`` (a real
        # response-model with no watermark) so the registry-entry
        # validator does not trip on the incremental-flag invariant.
        # ``name='odometer'`` because ``ResourceRegistryEntry.name`` is
        # narrowed to the ``EndpointName`` Literal — a stand-in like
        # ``'stub'`` would fail the discriminated-name validator before
        # the test reaches the assertion under examination.
        stub_entry: ResourceRegistryEntry = ResourceRegistryEntry(
            name='odometer',
            query_class=_StubQuery,
            response_class=Odometer,
            supports_incremental=False,
        )

        api_config: ApiConfig = ApiConfig(base_url=HttpUrl(_BASE_URL))
        fleet_config: FleetConfig = FleetConfig(lessee_codes=_LESSEE_CODES)

        query: QueryInputBase[ResponseModel] = build_query_from_filters(
            registry_entry=stub_entry,
            filters=_StubFilters(widget='hello'),
            api_config=api_config,
            fleet_config=fleet_config,
        )

        # Exactly the three inputs (query_class, base_url, lessee_codes)
        # plus the filter dump reach the query — nothing else.
        assert isinstance(query, _StubQuery)
        assert query.base_url == _BASE_URL + '/'
        assert query.lessee_codes == _LESSEE_CODES
        assert query.widget == 'hello'
