# src/pyholman/_endpoints/vehicles/query.py
"""
Transport-layer query input for the Holman vehicles endpoint.

``VehiclesQuery`` is a frozen slotted dataclass subclass of
:class:`pyholman._core.QueryInputBase`. It exists to describe one page
of a vehicles request: the endpoint path, the response model, and the
per-call filter values. The orchestrator builds it from a validated
:class:`VehiclesFilters`, :class:`pyholman.UserConfig.fleet.lessee_codes`,
and :class:`pyholman.UserConfig.api.base_url`; this module stays
unaware of both.

``sold_date_code`` is derived in :class:`VehiclesFilters`
(``@computed_field``) and passed in pre-resolved, so there is no
``__post_init__`` here — by the time values reach this dataclass they
have already been validated and composed.
"""

from dataclasses import dataclass, field
from typing import ClassVar

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.vehicles.response import Vehicle

__all__: list[str] = ['VehiclesQuery']


@dataclass(frozen=True, slots=True, kw_only=True)
class VehiclesQuery(QueryInputBase[Vehicle]):
    """
    Query input for Holman's vehicles ``basic-query`` endpoint.

    Attributes:
        status_codes: Optional tuple of statusCodes to include on the
            wire. Serialized as comma-joined (``statusCodes=0,1,2``).
        sold_date_code: Derived value that Holman requires when
            ``status_codes`` contains ``3``. Computed in
            :class:`VehiclesFilters`, not here.
    """

    endpoint_path: ClassVar[str] = '/CustomerDataAPI/vehicles/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = Vehicle

    status_codes: tuple[int, ...] | None = field(
        default=None,
        metadata={'api_key': 'statusCodes'},
    )
    sold_date_code: int | None = field(
        default=None,
        metadata={'api_key': 'soldDateCode'},
    )
