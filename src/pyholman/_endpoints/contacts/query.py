# src/pyholman/_endpoints/contacts/query.py
"""
Transport-layer query input for the contacts endpoint.

Frozen slotted dataclass subclass of
:class:`pyholman._core.QueryInputBase` with no endpoint-specific
instance fields. Every wire field this endpoint accepts is inherited
from the base class.
"""

from dataclasses import dataclass
from typing import ClassVar

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.contacts.response import Contact

__all__: list[str] = ['ContactQuery']


@dataclass(frozen=True, slots=True, kw_only=True)
class ContactQuery(QueryInputBase[Contact]):
    """Query input for Holman's contacts endpoint."""

    endpoint_path: ClassVar[str] = '/CustomerDataAPI/contacts/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = Contact
