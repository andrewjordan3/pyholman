# src/pyholman/_endpoints/odometer/response.py
"""
Response model for the Holman odometer endpoint.

One record from ``/CustomerDataAPI/odometer/basic-query`` is one
vehicle's current odometer reading: ``totalCount`` divided by
``pageSize`` matches the number of pages exactly on live pulls, which
means the endpoint returns one row per vehicle rather than a history.
The class is named ``Odometer`` to match that shape.

Wire-format rules the type annotations encode:
    - Numeric fields stay numeric: ``odometer``, ``icnNo``,
      ``odometerHistoryId``, ``vehicleId``, ``lastChangeRecordId`` are
      all ``int | None``.
    - String fields stay strings: ``holmanVehicleNumber``,
      ``clientVehicleNumber``, ``division``, ``prefix``, ``vin``,
      ``lesseeCode``, ``odometerSource``, ``odometerQuality``.
    - Date/datetime fields are ISO 8601 with ``Z`` suffix on the
      wire; Pydantic parses them into timezone-aware ``datetime``
      natively.
    - Every field is ``T | None`` with ``default=None``.
"""

from datetime import datetime

from pydantic import Field

from pyholman._core import ResponseModel

__all__: list[str] = ['Odometer']


class Odometer(ResponseModel):
    """One odometer reading as returned by Holman's odometer endpoint."""

    client_vehicle_number: str | None = Field(alias='clientVehicleNumber', default=None)
    division: str | None = None
    holman_vehicle_number: str | None = Field(alias='holmanVehicleNumber', default=None)
    icn_no: int | None = Field(alias='icnNo', default=None)
    last_change_date: datetime | None = Field(alias='lastChangeDate', default=None)
    last_change_record_id: int | None = Field(alias='lastChangeRecordId', default=None)
    lessee_code: str | None = Field(alias='lesseeCode', default=None)
    odometer: int | None = None
    odometer_date: datetime | None = Field(alias='odometerDate', default=None)
    odometer_history_id: int | None = Field(alias='odometerHistoryId', default=None)
    odometer_quality: str | None = Field(alias='odometerQuality', default=None)
    odometer_source: str | None = Field(alias='odometerSource', default=None)
    prefix: str | None = None
    vehicle_id: int | None = Field(alias='vehicleId', default=None)
    vin: str | None = None
