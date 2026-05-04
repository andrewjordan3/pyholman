# src/pyholman/_config/resources.py
"""
Per-endpoint user-facing resource configuration.

Each endpoint has a ``*ResourceConfig`` class that validates one entry
from the YAML ``resources:`` list. The classes are combined into the
:data:`ResourceConfig` discriminated union, keyed by the ``name``
field, so Pydantic resolves one YAML entry to the specific config
class at parse time — the orchestrator consumes a statically typed
tree rather than doing its own runtime dispatch.

Each variant carries:

    - ``name``: ``Literal`` discriminator matching the registered
      resource name (see :data:`pyholman._endpoints.registry.REGISTRY`).
    - ``incremental``: ``bool`` selecting delta vs. full refresh.
      Variants for snapshot-only endpoints (odometer, engine hours)
      enforce ``incremental=False`` via a post-validator.
    - ``filters``: the strict per-endpoint filter schema validated at
      config load time with ``extra='forbid'``, catching typos in
      filter keys before any HTTP request is issued.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pyholman._core import FrozenModel
from pyholman._endpoints.contacts import ContactFilters
from pyholman._endpoints.engine_hours import EngineHoursFilters
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderFilters,
)
from pyholman._endpoints.odometer import OdometerFilters
from pyholman._endpoints.vehicles import VehiclesFilters

__all__: list[str] = [
    'ContactsResourceConfig',
    'EngineHoursResourceConfig',
    'MaintenancePurchaseOrdersResourceConfig',
    'OdometerResourceConfig',
    'ResourceConfig',
    'VehiclesResourceConfig',
]


class VehiclesResourceConfig(FrozenModel):
    """
    User configuration for the vehicles resource.

    Attributes:
        name: Discriminator value selecting the vehicles resource.
        incremental: Whether this resource should use incremental
            refresh. ``False`` means full refresh.
        filters: Vehicles-specific filter values. Validated at config
            load against the :class:`VehiclesFilters` schema.
    """

    name: Literal['vehicles']
    incremental: bool = False
    filters: VehiclesFilters = Field(default_factory=VehiclesFilters)


class MaintenancePurchaseOrdersResourceConfig(FrozenModel):
    """
    User configuration for the maintenance purchase orders resource.

    Attributes:
        name: Discriminator value selecting the maintenance purchase
            orders resource.
        incremental: Whether this resource should use incremental
            refresh. ``False`` means full refresh.
        filters: Maintenance-PO-specific filter values. Validated at
            config load against the
            :class:`MaintenancePurchaseOrderFilters` schema.
    """

    name: Literal['maintenance_purchase_orders']
    incremental: bool = False
    filters: MaintenancePurchaseOrderFilters = Field(
        default_factory=MaintenancePurchaseOrderFilters
    )


class ContactsResourceConfig(FrozenModel):
    """
    User configuration for the contacts resource.

    Attributes:
        name: Discriminator value selecting the contacts resource.
        incremental: Whether this resource should use incremental
            refresh. ``False`` means full refresh.
        filters: Contacts-specific filter values. Validated at config
            load against the :class:`ContactFilters` schema.
    """

    name: Literal['contacts']
    incremental: bool = False
    filters: ContactFilters = Field(default_factory=ContactFilters)


class OdometerResourceConfig(FrozenModel):
    """
    User configuration for the odometer resource.

    The odometer endpoint is snapshot-only — a post-validator rejects
    ``incremental=True`` at config load time.

    Attributes:
        name: Discriminator value selecting the odometer resource.
        incremental: Must be ``False``. Declared for shape uniformity
            with the incremental-capable resources.
        filters: Odometer-specific filter values (currently none).
    """

    name: Literal['odometer']
    incremental: bool = False
    filters: OdometerFilters = Field(default_factory=OdometerFilters)

    @model_validator(mode='after')
    def _reject_incremental(self) -> Self:
        if self.incremental:
            raise ValueError(
                "resource 'odometer' does not support incremental pulls; "
                'set incremental: false or omit the field'
            )
        return self


class EngineHoursResourceConfig(FrozenModel):
    """
    User configuration for the engine hours resource.

    The engine hours endpoint is snapshot-only — a post-validator
    rejects ``incremental=True`` at config load time.

    Attributes:
        name: Discriminator value selecting the engine hours resource.
        incremental: Must be ``False``. Declared for shape uniformity
            with the incremental-capable resources.
        filters: Engine-hours-specific filter values (currently none).
    """

    name: Literal['engine_hours']
    incremental: bool = False
    filters: EngineHoursFilters = Field(default_factory=EngineHoursFilters)

    @model_validator(mode='after')
    def _reject_incremental(self) -> Self:
        if self.incremental:
            raise ValueError(
                "resource 'engine_hours' does not support incremental pulls; "
                'set incremental: false or omit the field'
            )
        return self


# Discriminated union keyed by the ``name`` literal on each variant.
# Pydantic resolves the correct variant at parse time, so downstream
# code sees a statically typed union rather than a loosely typed base.
type ResourceConfig = Annotated[
    VehiclesResourceConfig
    | MaintenancePurchaseOrdersResourceConfig
    | ContactsResourceConfig
    | OdometerResourceConfig
    | EngineHoursResourceConfig,
    Field(discriminator='name'),
]
