# src/pyholman/_endpoints/registry.py
"""
Endpoint registry — maps resource names to runtime metadata.

The registry is the bridge between the user-facing
:class:`pyholman._config.ResourceConfig` (what the user wants to pull)
and the orchestrator (how pyholman fulfills the request). It carries
the pieces the orchestrator needs that do not belong in user-facing
configuration: the query class to construct, the response class to
parse into, and whether incremental is supported.

The per-endpoint *filter* class is deliberately NOT on the registry
— filters are resolved statically through the discriminated
:class:`pyholman._config.ResourceConfig` union at config load time.
Keeping filters off the registry means the orchestrator never does
runtime dispatch on resource name to choose a filter shape: the
config object it receives already carries the correctly typed filter.

The on-disk directory name is also not on the registry: the convention
is "directory name equals resource name", and the concrete
:class:`pyholman._storage.StorageHandler` for each resource constructs
its data and metadata paths directly from the resource name. Storing
the directory name as a separate field would invite drift — the
orchestrator now uses ``entry.name`` directly.

:data:`EndpointName` is the source of truth for the *set* of registered
endpoint names. :data:`ENDPOINT_NAMES` is the runtime tuple derived
from it. Adding a new endpoint requires adding a literal to
``EndpointName`` plus an entry to :data:`REGISTRY`. The per-
``*ResourceConfig`` discriminator literals (``Literal['vehicles']`` on
:class:`VehiclesResourceConfig` and friends) are deliberately not
consolidated into ``EndpointName`` — Pydantic's discriminated-union
dispatch requires the per-class form on each variant, structurally
different from the broad union literal here.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, Self, get_args

from pydantic import model_validator

from pyholman._core import FrozenModel, QueryInputBase, ResponseModel
from pyholman._endpoints.contacts import Contact, ContactQuery
from pyholman._endpoints.engine_hours import EngineHours, EngineHoursQuery
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrder,
    MaintenancePurchaseOrderQuery,
)
from pyholman._endpoints.odometer import Odometer, OdometerQuery
from pyholman._endpoints.vehicles import Vehicle, VehiclesQuery

__all__: list[str] = [
    'ENDPOINT_NAMES',
    'REGISTRY',
    'EndpointName',
    'ResourceRegistryEntry',
    'get_registry_entry',
]


EndpointName = Literal[
    'vehicles',
    'maintenance_purchase_orders',
    'contacts',
    'odometer',
    'engine_hours',
]

# Runtime tuple of registered endpoint names, derived from
# :data:`EndpointName` so the two cannot drift. Use this for membership
# checks and iteration; use :data:`EndpointName` for type annotations.
ENDPOINT_NAMES: Final[tuple[EndpointName, ...]] = get_args(EndpointName)


class ResourceRegistryEntry(FrozenModel):
    """
    Registry entry describing one endpoint's runtime metadata.

    Populated at module import time, validated immediately, frozen.

    Attributes:
        name: Canonical resource name — one of the
            :data:`EndpointName` literals. Matches the discriminator
            literal on the paired :class:`ResourceConfig` variant,
            the directory name under ``src/pyholman/_endpoints/``,
            and the on-disk output directory name under the working
            directory.
        query_class: :class:`pyholman._core.QueryInputBase` subclass
            the orchestrator constructs to issue requests for this
            endpoint.
        response_class: :class:`pyholman._core.ResponseModel` subclass
            the orchestrator parses each response item into.
        supports_incremental: ``True`` when this endpoint can be pulled
            with an incremental delta (anchored on the response model's
            ``watermark_column``); ``False`` for snapshot-only endpoints.
    """

    name: EndpointName
    query_class: type[QueryInputBase]
    response_class: type[ResponseModel]
    supports_incremental: bool

    @model_validator(mode='after')
    def _validate_watermark_consistency(self) -> Self:
        """
        Enforce that ``supports_incremental`` and
        ``response_class.watermark_column`` agree.

        Raises:
            ValueError: If the flags disagree in either direction.
        """
        watermark: str | None = self.response_class.watermark_column
        if self.supports_incremental and watermark is None:
            raise ValueError(
                f"resource '{self.name}' has supports_incremental=True but "
                f'response class {self.response_class.__name__} declares no '
                f'watermark_column; add a ClassVar on the response model or '
                f'set supports_incremental=False'
            )
        if not self.supports_incremental and watermark is not None:
            raise ValueError(
                f"resource '{self.name}' has supports_incremental=False but "
                f'response class {self.response_class.__name__} declares '
                f'watermark_column={watermark!r}; either remove the override '
                f'or set supports_incremental=True'
            )
        return self


def _build_registry() -> Mapping[str, ResourceRegistryEntry]:
    """
    Return the immutable resource registry keyed by resource name.

    The mapping is typed ``Mapping[str, ...]`` rather than
    ``Mapping[EndpointName, ...]`` so :func:`get_registry_entry` can
    look up an arbitrary user-supplied string and surface a friendly
    ``ValueError`` for unknown names. The ``EndpointName`` narrowing
    lives on the entry's ``name`` field, where the validator enforces
    it; the dict-key type is the runtime ergonomic choice.
    """
    entries: tuple[ResourceRegistryEntry, ...] = (
        ResourceRegistryEntry(
            name='vehicles',
            query_class=VehiclesQuery,
            response_class=Vehicle,
            supports_incremental=True,
        ),
        ResourceRegistryEntry(
            name='maintenance_purchase_orders',
            query_class=MaintenancePurchaseOrderQuery,
            response_class=MaintenancePurchaseOrder,
            supports_incremental=True,
        ),
        ResourceRegistryEntry(
            name='contacts',
            query_class=ContactQuery,
            response_class=Contact,
            supports_incremental=True,
        ),
        ResourceRegistryEntry(
            name='odometer',
            query_class=OdometerQuery,
            response_class=Odometer,
            supports_incremental=False,
        ),
        ResourceRegistryEntry(
            name='engine_hours',
            query_class=EngineHoursQuery,
            response_class=EngineHours,
            supports_incremental=False,
        ),
    )
    return MappingProxyType({entry.name: entry for entry in entries})


REGISTRY: Final[Mapping[str, ResourceRegistryEntry]] = _build_registry()


def get_registry_entry(name: str) -> ResourceRegistryEntry:
    """
    Return the registry entry for ``name``, or raise ``ValueError``.

    Args:
        name: Canonical resource name (e.g., ``'vehicles'``).

    Returns:
        The matching :class:`ResourceRegistryEntry`.

    Raises:
        ValueError: If ``name`` is not a registered resource. The error
            message names the unknown resource and lists the registered
            names for user-friendly diagnostics.
    """
    entry: ResourceRegistryEntry | None = REGISTRY.get(name)
    if entry is None:
        known: str = ', '.join(sorted(REGISTRY))
        raise ValueError(
            f'unknown resource {name!r}; registered resources are: {known}'
        )
    return entry
