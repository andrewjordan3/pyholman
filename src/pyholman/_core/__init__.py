# src/pyholman/_core/__init__.py
"""
Pyholman Pydantic base models, pagination envelope, and query base.

External callers — code outside the ``pyholman._core`` package — should
import from this module. Internal callers within the package import
directly from sibling modules (for example, ``ResponseModel`` and
``FrozenModel`` import ``BaseHolmanModel`` from
``pyholman._core.base``), keeping this ``__init__.py`` a thin
re-export layer rather than a routing point for intra-package imports.
"""

from pyholman._core.filters import IncrementalFilters
from pyholman._core.frozen import FrozenModel
from pyholman._core.query import QueryInputBase
from pyholman._core.response import PageInfo, PaginatedResponse, ResponseModel

__all__: list[str] = [
    'FrozenModel',
    'IncrementalFilters',
    'PageInfo',
    'PaginatedResponse',
    'QueryInputBase',
    'ResponseModel',
]
