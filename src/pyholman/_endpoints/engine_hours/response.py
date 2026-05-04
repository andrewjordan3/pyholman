# src/pyholman/_endpoints/engine_hours/response.py
"""
Response model for the Holman engine hours endpoint.

One record from ``/CustomerDataAPI/engine-hours/basic-query`` is one
vehicle's engine-hour reading — alongside the odometer endpoint in
shape and role, minus the ``odometerQuality`` field.

Wire-format note: Holman is inconsistent about the casing of the
``hour*meter*`` fields within a single response — three use lowercase
``m`` (``hourmeter``, ``hourmeterDate``, ``hourmeterSource``) and one
uses uppercase ``M`` (``hourMeterHistoryId``). The Pydantic aliases
must match the wire literally; the model-attribute names normalize to
consistent snake_case (``hour_meter``, ``hour_meter_date``,
``hour_meter_source``, ``hour_meter_history_id``).
"""

from datetime import datetime

from pydantic import Field

from pyholman._core import ResponseModel

__all__: list[str] = ['EngineHours']


class EngineHours(ResponseModel):
    """One engine-hour reading as returned by Holman's engine-hours endpoint."""

    client_vehicle_number: str | None = Field(alias='clientVehicleNumber', default=None)
    division: str | None = None
    holman_vehicle_number: str | None = Field(alias='holmanVehicleNumber', default=None)

    # Aliases below mirror Holman's inconsistent wire casing exactly —
    # three fields use lowercase ``hourmeter*`` and ``hour_meter_history_id``
    # uses capital-M ``hourMeterHistoryId``. Do not "fix" the aliases to be
    # consistent; parsing against a live response depends on this match.
    hour_meter: int | None = Field(alias='hourmeter', default=None)
    hour_meter_date: datetime | None = Field(alias='hourmeterDate', default=None)
    hour_meter_history_id: int | None = Field(alias='hourMeterHistoryId', default=None)
    hour_meter_source: str | None = Field(alias='hourmeterSource', default=None)

    icn_no: int | None = Field(alias='icnNo', default=None)
    last_change_date: datetime | None = Field(alias='lastChangeDate', default=None)
    last_change_record_id: int | None = Field(alias='lastChangeRecordId', default=None)
    lessee_code: str | None = Field(alias='lesseeCode', default=None)
    prefix: str | None = None
    vehicle_id: int | None = Field(alias='vehicleId', default=None)
    vin: str | None = None
