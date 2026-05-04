# src/pyholman/_endpoints/engine_hours/filters.py
"""
User-facing filter model for the engine hours endpoint.

Empty of user-settable fields, mirroring :class:`OdometerFilters`.
Two omissions are deliberate; both are documented on the class
docstring so a future reader does not "fix" them:

    - ``last_change_date`` is not exposed. Whether Holman's engine hours
      endpoint silently hangs on the parameter the way the odometer
      endpoint does has not been verified against a live response; the
      conservative posture until it is verified safe matches odometer.
    - ``hourmeter_hist_date_code`` is deferred pending a unified
      date-code abstraction (several endpoints accept sibling parameters
      under different names — ``soldDateCode`` on vehicles,
      ``odometerHistoryDateCode`` on odometer, ``hourmeterHistDateCode``
      here).
"""

from pyholman._core import FrozenModel

__all__: list[str] = ['EngineHoursFilters']


class EngineHoursFilters(FrozenModel):
    """
    Validated user-facing filters for the engine hours endpoint.

    No user-settable fields today. ``FrozenModel``'s inherited
    ``extra='forbid'`` means any key a user writes under ``filters:``
    in YAML surfaces as a clear config-load error rather than being
    silently dropped.

    Deliberate omissions (see module docstring for the full reasoning):
        - ``last_change_date``: unverified whether Holman hangs on it.
        - ``hourmeter_hist_date_code``: deferred for unified date-code
          handling.
    """
