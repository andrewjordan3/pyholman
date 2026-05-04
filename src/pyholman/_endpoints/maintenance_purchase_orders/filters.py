# src/pyholman/_endpoints/maintenance_purchase_orders/filters.py
"""
User-facing filter model for the maintenance purchase orders endpoint.

Deliberately minimal. Users authoring YAML for this resource will most
often write nothing under ``filters:`` — the orchestrator scopes the
request via ``lessee_codes`` and the incremental cursor on its own.
The single user-settable value is ``last_change_date``, which
participates in window resolution alongside
``incremental.earliest_date`` and (on steady-state runs) the prior
watermark minus ``lookback_days``; the more recent of those
candidates wins and the result is clamped up to ``earliest_date`` if
that floor is set. Both the field and its tz-aware UTC validation
live on :class:`IncrementalFilters`.
"""

from pyholman._core import IncrementalFilters

__all__: list[str] = ['MaintenancePurchaseOrderFilters']


class MaintenancePurchaseOrderFilters(IncrementalFilters):
    """
    Validated user-facing filters for the maintenance purchase orders endpoint.

    Inherits from :class:`IncrementalFilters` — supplies the
    ``last_change_date`` cursor field and the ``with_window_start``
    override for incremental refresh runs.
    """
