# src/pyholman/_endpoints/maintenance_purchase_orders/query.py
"""
Transport-layer query input for the maintenance purchase orders endpoint.

Frozen slotted dataclass subclass of
:class:`pyholman._core.QueryInputBase`. It carries no endpoint-specific
filter fields — every wire field this endpoint accepts (``base_url``,
``lessee_codes``, ``last_change_date``, ``last_change_record_id``) is
inherited from the base. The subclass body is just the two ``ClassVar``
attributes that bind the path and the response item type.
"""

from dataclasses import dataclass
from typing import ClassVar

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.maintenance_purchase_orders.response import (
    MaintenancePurchaseOrder,
)

__all__: list[str] = ['MaintenancePurchaseOrderQuery']


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenancePurchaseOrderQuery(QueryInputBase[MaintenancePurchaseOrder]):
    """Query input for Holman's maintenance purchase orders endpoint."""

    endpoint_path: ClassVar[str] = (
        '/CustomerDataAPI/maintenance/purchase-orders/basic-query'
    )
    response_item_type: ClassVar[type[ResponseModel]] = MaintenancePurchaseOrder
