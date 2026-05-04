# src/pyholman/_endpoints/engine_hours/query.py
"""
Transport-layer query input for the engine hours endpoint.

Frozen slotted dataclass subclass of
:class:`pyholman._core.QueryInputBase` with no endpoint-specific
instance fields. Every wire field this endpoint accepts is inherited
from the base class.
"""

from dataclasses import dataclass
from typing import ClassVar

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.engine_hours.response import EngineHours

__all__: list[str] = ['EngineHoursQuery']


@dataclass(frozen=True, slots=True, kw_only=True)
class EngineHoursQuery(QueryInputBase[EngineHours]):
    """Query input for Holman's engine hours endpoint."""

    endpoint_path: ClassVar[str] = '/CustomerDataAPI/engine-hours/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = EngineHours
