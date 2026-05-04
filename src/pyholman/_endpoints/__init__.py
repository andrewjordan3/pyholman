# src/pyholman/_endpoints/__init__.py
"""
Endpoint-specific query + response pairs.

Each endpoint lives in its own subpackage here — one package holds the
:class:`pyholman._core.QueryInputBase` subclass, the paired
:class:`pyholman._core.ResponseModel`, and (where applicable) the
user-facing filter model for a single Holman endpoint (vehicles,
contacts, maintenance, and so on). Endpoints are not re-exported from
this ``__init__.py``; callers import from the endpoint subpackage
directly (``from pyholman._endpoints.vehicles import ...``).
"""

__all__: list[str] = []
