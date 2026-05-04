# src/pyholman/_endpoints/odometer/filters.py
"""
User-facing filter model for the odometer endpoint.

The class has no fields today; it exists to give the endpoint a
filter-model seat in the orchestrator architecture without demanding
a future change in module shape when fields do land. Two omissions
are deliberate, both documented on the class docstring so a future
reader does not "fix" them:

    - ``last_change_date`` is not exposed. Holman's odometer endpoint
      silently hangs until timeout when the parameter is sent, even
      though it accepts the request without error. Incremental pulls
      against this endpoint use ``last_change_record_id`` instead.
    - ``odometer_history_date_code`` is deferred until a unified
      date-code abstraction emerges (several endpoints accept sibling
      parameters under different names).
"""

from pyholman._core import FrozenModel

__all__: list[str] = ['OdometerFilters']


class OdometerFilters(FrozenModel):
    """
    Validated user-facing filters for the odometer endpoint.

    No user-settable fields today. ``FrozenModel``'s inherited
    ``extra='forbid'`` means any key a user writes under ``filters:``
    in YAML surfaces as a clear config-load error rather than being
    silently dropped.

    Deliberate omissions (see module docstring for the full reasoning):
        - ``last_change_date``: Holman's endpoint hangs on the parameter.
        - ``odometer_history_date_code``: deferred for unified date-code
          handling.
    """
