# tests/_endpoints/test_filters_incremental_consistency.py
"""
Drift-guard between registry ``supports_incremental`` and filter base.

For every registered resource:

    - If ``supports_incremental=True``, the corresponding
      ``*ResourceConfig.filters`` annotation must be an
      ``IncrementalFilters`` subclass.
    - If ``supports_incremental=False``, the filter annotation must
      NOT be an ``IncrementalFilters`` subclass.

Catches the case where someone flips a registry entry's flag without
updating the filter base — the runner relies on the base class for
its ``with_window_start`` override path and an inconsistent state
would only surface at runtime.
"""

from typing import get_args, get_origin

import pytest

from pyholman._config.resources import (
    ContactsResourceConfig,
    EngineHoursResourceConfig,
    MaintenancePurchaseOrdersResourceConfig,
    OdometerResourceConfig,
    VehiclesResourceConfig,
)
from pyholman._core import FrozenModel, IncrementalFilters
from pyholman._endpoints.registry import REGISTRY

__all__: list[str] = []


_RESOURCE_CONFIG_FOR_NAME: dict[str, type[FrozenModel]] = {
    'vehicles': VehiclesResourceConfig,
    'maintenance_purchase_orders': MaintenancePurchaseOrdersResourceConfig,
    'contacts': ContactsResourceConfig,
    'odometer': OdometerResourceConfig,
    'engine_hours': EngineHoursResourceConfig,
}


def _filter_class_from_resource_config(
    resource_config_class: type[FrozenModel],
) -> type[FrozenModel]:
    """Resolve the concrete filter class declared on the ``filters`` field."""
    field_info = resource_config_class.model_fields['filters']
    annotation = field_info.annotation
    # Pydantic v2 stores the raw annotation. For these classes the
    # annotation is the concrete filter class directly (no Optional or
    # Annotated wrappers); fall back to ``get_args`` defensively in
    # case a future change wraps it.
    if get_origin(annotation) is None:
        assert isinstance(annotation, type)
        return annotation
    inner_args = [arg for arg in get_args(annotation) if isinstance(arg, type)]
    assert len(inner_args) == 1, (
        f'unexpected wrapped annotation on {resource_config_class.__name__}.filters: '
        f'{annotation!r}'
    )
    return inner_args[0]


@pytest.mark.parametrize('resource_name', sorted(_RESOURCE_CONFIG_FOR_NAME))
def test_supports_incremental_matches_filter_base(resource_name: str) -> None:
    registry_entry = REGISTRY[resource_name]
    resource_config_class = _RESOURCE_CONFIG_FOR_NAME[resource_name]
    filter_class = _filter_class_from_resource_config(resource_config_class)

    is_incremental_filter: bool = issubclass(filter_class, IncrementalFilters)

    assert is_incremental_filter is registry_entry.supports_incremental, (
        f'drift detected for {resource_name!r}: '
        f'supports_incremental={registry_entry.supports_incremental} '
        f'but filter class {filter_class.__name__} '
        f'IncrementalFilters subclass={is_incremental_filter}'
    )
