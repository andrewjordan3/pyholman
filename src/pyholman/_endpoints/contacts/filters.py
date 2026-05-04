# src/pyholman/_endpoints/contacts/filters.py
"""
User-facing filter model for the contacts endpoint.

The contacts endpoint is registered with ``supports_incremental=True``;
the universal ``last_change_date`` cursor and its tz-aware UTC validation
live on :class:`IncrementalFilters`. Users may set the field directly in
YAML; it participates in window resolution alongside
``incremental.earliest_date`` and (on steady-state runs) the prior
watermark minus ``lookback_days``.

Other Holman date-code parameters (``hire_date_code``,
``activation_date_code``, ``deactivation_date_code``,
``termination_date_code``) are deferred pending a unified date-code
abstraction.
"""

from pyholman._core import IncrementalFilters

__all__: list[str] = ['ContactFilters']


class ContactFilters(IncrementalFilters):
    """
    Validated user-facing filters for the contacts endpoint.

    Inherits from :class:`IncrementalFilters` — supplies the
    ``last_change_date`` cursor field and the ``with_window_start``
    override for incremental refresh runs.

    Deliberate omissions (date-code parameters):
        - ``hire_date_code``, ``activation_date_code``,
          ``deactivation_date_code``, ``termination_date_code``:
          deferred for unified date-code handling. ``extra='forbid'``
          inherited from :class:`IncrementalFilters` rejects any of
          these keys at config load time.
    """
