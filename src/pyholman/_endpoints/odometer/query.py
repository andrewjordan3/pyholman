# src/pyholman/_endpoints/odometer/query.py
"""
Transport-layer query input for the odometer endpoint.

Frozen slotted dataclass subclass of
:class:`pyholman._core.QueryInputBase` with no endpoint-specific
instance fields. ``base_url``, ``lessee_codes``,
``last_change_record_id``, and ``last_change_date`` are inherited.

The inherited ``last_change_date`` stays on the base class even though
Holman's odometer endpoint silently hangs when the parameter is sent:
:class:`OdometerFilters` is the layer that prevents user YAML from
populating it, and the base-class default of ``None`` means the field
never appears on the wire for unset queries.
"""

from dataclasses import dataclass
from typing import ClassVar

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.odometer.response import Odometer

__all__: list[str] = ['OdometerQuery']


@dataclass(frozen=True, slots=True, kw_only=True)
class OdometerQuery(QueryInputBase[Odometer]):
    """Query input for Holman's odometer endpoint."""

    endpoint_path: ClassVar[str] = '/CustomerDataAPI/odometer/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = Odometer
