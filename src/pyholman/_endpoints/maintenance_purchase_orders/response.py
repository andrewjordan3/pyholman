# src/pyholman/_endpoints/maintenance_purchase_orders/response.py
"""
Response model for the Holman maintenance purchase orders endpoint.

``MaintenancePurchaseOrder`` mirrors one record from the live
``basic-query`` payload at ``/CustomerDataAPI/maintenance/purchase-orders``.
The model is parameterized into
:class:`pyholman._core.PaginatedResponse` at the point of use.

Wire-format rules the type annotations encode:
    - Numeric fields stay numeric. Unlike the vehicles endpoint, where
      ``odometer`` is a string-typed field, the maintenance endpoint
      sends ``odometer`` as an integer (``173367``) and the model
      reflects that. ``hourMeter``, ``poNumber``, ``poDetailsId``,
      ``poLineNumber``, and ``lastChangeRecordId`` are also integers.
    - Decimal numeric fields are ``float | None``. ``cost`` and
      ``poTotalLineCost`` arrive as either int-shaped (``0``, ``175``)
      or decimal-shaped (``336.09``) and ``quantity`` arrives as
      either int-shaped (``1``) or fractional (``0.5``, ``0.25``,
      ``2.84`` — labor hours are commonly fractional). ``float``
      covers both shapes.
    - Strings stay strings even when they look numeric: ``vendorId``
      is alphanumeric (``"000000XX"``), ``ataCode`` is a code, and
      ``customerPoNumber`` / ``invoiceNumber`` are identifiers.
    - Date/datetime fields are ISO 8601 with ``Z`` suffix on the wire;
      Pydantic parses them into timezone-aware ``datetime`` natively.
    - Almost every field is nullable on some record. Every field is
      typed ``T | None`` and defaults to ``None``.

Wire over docs:
    Holman's reference PDF and the live wire format disagree about
    several numeric fields' types — ``cost`` and ``poTotalLineCost``
    are documented inconsistently across pages, and ``quantity`` is
    documented as ``string(6,2)`` while the wire returns a JSON
    number. When the docs and the wire disagree, pyholman matches the
    wire. The wire is what we have to parse; documentation drift is
    Holman's to fix.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import Field

from pyholman._core import ResponseModel

__all__: list[str] = ['MaintenancePurchaseOrder']


class MaintenancePurchaseOrder(ResponseModel):
    """
    One purchase-order line as returned by Holman's maintenance endpoint.

    A "purchase order" in Holman's vocabulary is one *line* on a maintenance
    invoice; multiple records share a ``po_number`` and differ only by
    ``po_line_number`` and ``po_details_id``. The model is line-grained
    because that is the wire shape; orchestrator code that wants to
    aggregate by PO can group on ``po_number`` itself.

    Field names follow pyholman's convention: Python attributes are
    snake_case, Pydantic aliases mirror Holman's camelCase wire names.
    """

    # Incremental pulls watermark on ``last_change_date`` (Holman's
    # ``lastChangeDate`` on the wire).
    watermark_column: ClassVar[str | None] = 'last_change_date'

    ata_code: str | None = Field(alias='ataCode', default=None)
    ata_description: str | None = Field(alias='ataDescription', default=None)

    aux_data_1: str | None = Field(alias='auxData1', default=None)
    aux_data_2: str | None = Field(alias='auxData2', default=None)
    aux_data_3: str | None = Field(alias='auxData3', default=None)
    aux_data_4: str | None = Field(alias='auxData4', default=None)
    aux_data_5: str | None = Field(alias='auxData5', default=None)
    aux_data_6: str | None = Field(alias='auxData6', default=None)
    aux_data_7: str | None = Field(alias='auxData7', default=None)
    aux_data_8: str | None = Field(alias='auxData8', default=None)
    aux_data_9: str | None = Field(alias='auxData9', default=None)
    aux_data_10: str | None = Field(alias='auxData10', default=None)
    aux_data_11: str | None = Field(alias='auxData11', default=None)
    aux_data_12: str | None = Field(alias='auxData12', default=None)
    aux_data_13: str | None = Field(alias='auxData13', default=None)
    aux_data_14: str | None = Field(alias='auxData14', default=None)

    aux_date_1: datetime | None = Field(alias='auxDate1', default=None)
    aux_date_2: datetime | None = Field(alias='auxDate2', default=None)
    aux_date_3: datetime | None = Field(alias='auxDate3', default=None)
    aux_date_4: datetime | None = Field(alias='auxDate4', default=None)

    bill_paid_date: datetime | None = Field(alias='billPaidDate', default=None)
    cause: str | None = None

    client_data_1: str | None = Field(alias='clientData1', default=None)
    client_data_2: str | None = Field(alias='clientData2', default=None)
    client_data_3: str | None = Field(alias='clientData3', default=None)
    client_data_4: str | None = Field(alias='clientData4', default=None)
    client_data_5: str | None = Field(alias='clientData5', default=None)
    client_data_6: str | None = Field(alias='clientData6', default=None)
    client_data_7: str | None = Field(alias='clientData7', default=None)

    client_vehicle_number: str | None = Field(alias='clientVehicleNumber', default=None)
    complaint: str | None = None
    cost: float | None = None
    customer_po_number: str | None = Field(alias='customerPoNumber', default=None)
    division: str | None = None
    driver_class: str | None = Field(alias='driverClass', default=None)
    exec_: str | None = Field(alias='exec', default=None)
    first_name: str | None = Field(alias='firstName', default=None)
    holman_vehicle_number: str | None = Field(alias='holmanVehicleNumber', default=None)
    hour_meter: int | None = Field(alias='hourMeter', default=None)
    invoice_date: datetime | None = Field(alias='invoiceDate', default=None)
    invoice_number: str | None = Field(alias='invoiceNumber', default=None)
    last_change_date: datetime | None = Field(alias='lastChangeDate', default=None)
    last_change_record_id: int | None = Field(alias='lastChangeRecordId', default=None)
    last_name: str | None = Field(alias='lastName', default=None)
    lessee_code: str | None = Field(alias='lesseeCode', default=None)
    odometer: int | None = None
    po_date: datetime | None = Field(alias='poDate', default=None)
    po_details_id: int | None = Field(alias='poDetailsId', default=None)
    po_line_number: int | None = Field(alias='poLineNumber', default=None)
    po_number: int | None = Field(alias='poNumber', default=None)
    po_total_line_cost: float | None = Field(alias='poTotalLineCost', default=None)
    prefix: str | None = None
    quantity: float | None = None
    repair_date: datetime | None = Field(alias='repairDate', default=None)
    type_: str | None = Field(alias='type', default=None)
    vendor_address_line_1: str | None = Field(alias='vendorAddressLine1', default=None)
    vendor_address_line_2: str | None = Field(alias='vendorAddressLine2', default=None)
    vendor_city: str | None = Field(alias='vendorCity', default=None)
    vendor_id: str | None = Field(alias='vendorId', default=None)
    vendor_name: str | None = Field(alias='vendorName', default=None)
    vendor_state_province: str | None = Field(alias='vendorStateProvince', default=None)
    vendor_type: str | None = Field(alias='vendorType', default=None)
    vendor_zip_postal_code: str | None = Field(
        alias='vendorZipPostalCode', default=None
    )
    vin: str | None = None
