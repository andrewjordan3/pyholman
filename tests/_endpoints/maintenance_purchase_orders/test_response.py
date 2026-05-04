# tests/_endpoints/maintenance_purchase_orders/test_response.py
"""Tests for the MaintenancePurchaseOrder response model against live payloads."""

from datetime import UTC, datetime
from typing import Final

from pyholman._core import PaginatedResponse
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrder,
)

__all__: list[str] = []


_SAMPLE_PAGE_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 75314,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 3,
    "totalPages": 25105,
    "lastChangeRecordId": 100000004
  },
  "items": [
    {
      "ataCode": "1D001004",
      "ataDescription": "OUT OF NETWORK FEE",
      "auxData1": null,
      "auxData10": null,
      "auxData11": null,
      "auxData12": null,
      "auxData13": null,
      "auxData14": null,
      "auxData2": null,
      "auxData3": null,
      "auxData4": null,
      "auxData5": null,
      "auxData6": null,
      "auxData7": null,
      "auxData8": null,
      "auxData9": null,
      "auxDate1": null,
      "auxDate2": null,
      "auxDate3": null,
      "auxDate4": null,
      "billPaidDate": "2025-07-08T00:00:00Z",
      "cause": "NOT SUPPLIED",
      "clientData1": null,
      "clientData2": null,
      "clientData3": null,
      "clientData4": null,
      "clientData5": null,
      "clientData6": null,
      "clientData7": null,
      "clientVehicleNumber": null,
      "complaint": "NOT SUPPLIED",
      "cost": 0,
      "customerPoNumber": "0000000",
      "division": null,
      "driverClass": null,
      "exec": null,
      "firstName": null,
      "holmanVehicleNumber": "999999",
      "hourMeter": null,
      "invoiceDate": "2025-07-08T00:00:00Z",
      "invoiceNumber": "INV0000000",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lastName": null,
      "lesseeCode": "XXXX",
      "odometer": 173367,
      "poDate": "2025-07-08T00:00:00Z",
      "poDetailsId": 100000001,
      "poLineNumber": 1,
      "poNumber": 100000000,
      "poTotalLineCost": 0,
      "prefix": null,
      "quantity": 1,
      "repairDate": "2025-07-08T00:00:00Z",
      "type": "O",
      "vendorAddressLine1": "4001 LEADENHALL RD",
      "vendorAddressLine2": null,
      "vendorCity": "MOUNT LAUREL",
      "vendorId": "000000XX",
      "vendorName": "HISTORY PO ACCOUNT",
      "vendorStateProvince": "NJ",
      "vendorType": "IV",
      "vendorZipPostalCode": "08054",
      "vin": "1XXXXXXXXXXXXXXXX"
    },
    {
      "ataCode": "14004021",
      "ataDescription": "BODY REPAIRS BOLTS,BOX U-BOLTS,BOX BOLT",
      "auxData1": null,
      "auxData10": null,
      "auxData11": null,
      "auxData12": null,
      "auxData13": null,
      "auxData14": null,
      "auxData2": null,
      "auxData3": null,
      "auxData4": null,
      "auxData5": null,
      "auxData6": null,
      "auxData7": null,
      "auxData8": null,
      "auxData9": null,
      "auxDate1": null,
      "auxDate2": null,
      "auxDate3": null,
      "auxDate4": null,
      "billPaidDate": "2025-07-08T00:00:00Z",
      "cause": "NOT SUPPLIED",
      "clientData1": null,
      "clientData2": null,
      "clientData3": null,
      "clientData4": null,
      "clientData5": null,
      "clientData6": null,
      "clientData7": null,
      "clientVehicleNumber": null,
      "complaint": "NOT SUPPLIED",
      "cost": 175,
      "customerPoNumber": "0000000",
      "division": null,
      "driverClass": null,
      "exec": null,
      "firstName": null,
      "holmanVehicleNumber": "999999",
      "hourMeter": null,
      "invoiceDate": "2025-07-08T00:00:00Z",
      "invoiceNumber": "INV0000000",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lastName": null,
      "lesseeCode": "XXXX",
      "odometer": 173367,
      "poDate": "2025-07-08T00:00:00Z",
      "poDetailsId": 100000002,
      "poLineNumber": 2,
      "poNumber": 100000000,
      "poTotalLineCost": 175,
      "prefix": null,
      "quantity": 1,
      "repairDate": "2025-07-08T00:00:00Z",
      "type": "O",
      "vendorAddressLine1": "4001 LEADENHALL RD",
      "vendorAddressLine2": null,
      "vendorCity": "MOUNT LAUREL",
      "vendorId": "000000XX",
      "vendorName": "HISTORY PO ACCOUNT",
      "vendorStateProvince": "NJ",
      "vendorType": "IV",
      "vendorZipPostalCode": "08054",
      "vin": "1XXXXXXXXXXXXXXXX"
    },
    {
      "ataCode": "1E001002",
      "ataDescription": "OIL COST PER QUART",
      "auxData1": null,
      "auxData10": null,
      "auxData11": null,
      "auxData12": null,
      "auxData13": null,
      "auxData14": null,
      "auxData2": null,
      "auxData3": null,
      "auxData4": null,
      "auxData5": null,
      "auxData6": null,
      "auxData7": null,
      "auxData8": null,
      "auxData9": null,
      "auxDate1": null,
      "auxDate2": null,
      "auxDate3": null,
      "auxDate4": null,
      "billPaidDate": "2025-07-08T00:00:00Z",
      "cause": "NOT SUPPLIED",
      "clientData1": null,
      "clientData2": null,
      "clientData3": null,
      "clientData4": null,
      "clientData5": null,
      "clientData6": null,
      "clientData7": null,
      "clientVehicleNumber": null,
      "complaint": "NOT SUPPLIED",
      "cost": 336.09,
      "customerPoNumber": "0000000",
      "division": null,
      "driverClass": null,
      "exec": null,
      "firstName": null,
      "holmanVehicleNumber": "999999",
      "hourMeter": null,
      "invoiceDate": "2025-07-08T00:00:00Z",
      "invoiceNumber": "INV0000000",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lastName": null,
      "lesseeCode": "XXXX",
      "odometer": 173367,
      "poDate": "2025-07-08T00:00:00Z",
      "poDetailsId": 100000003,
      "poLineNumber": 3,
      "poNumber": 100000000,
      "poTotalLineCost": 336.09,
      "prefix": null,
      "quantity": 1,
      "repairDate": "2025-07-08T00:00:00Z",
      "type": "O",
      "vendorAddressLine1": "4001 LEADENHALL RD",
      "vendorAddressLine2": null,
      "vendorCity": "MOUNT LAUREL",
      "vendorId": "000000XX",
      "vendorName": "HISTORY PO ACCOUNT",
      "vendorStateProvince": "NJ",
      "vendorType": "IV",
      "vendorZipPostalCode": "08054",
      "vin": "1XXXXXXXXXXXXXXXX"
    }
  ]
}
"""

# Real-world wire payloads include fractional ``quantity`` values —
# half-hour labor (``0.5``, ``1.5``), quarter-hour and finer
# (``0.25``, ``0.33``), and other decimals. The values below are
# representative samples from a live first pull. Keeping the rest of
# each item identical to the int-shaped fixture isolates ``quantity``
# as the variable under test.
_FRACTIONAL_QUANTITY_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 3,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 3,
    "totalPages": 1,
    "lastChangeRecordId": 100000004
  },
  "items": [
    {
      "ataCode": "1D001004",
      "holmanVehicleNumber": "999999",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lesseeCode": "XXXX",
      "poDetailsId": 100000001,
      "poLineNumber": 1,
      "poNumber": 100000000,
      "quantity": 0.5
    },
    {
      "ataCode": "1D001004",
      "holmanVehicleNumber": "999999",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lesseeCode": "XXXX",
      "poDetailsId": 100000002,
      "poLineNumber": 2,
      "poNumber": 100000000,
      "quantity": 0.25
    },
    {
      "ataCode": "1D001004",
      "holmanVehicleNumber": "999999",
      "lastChangeDate": "2026-01-28T18:06:36Z",
      "lastChangeRecordId": 100000004,
      "lesseeCode": "XXXX",
      "poDetailsId": 100000003,
      "poLineNumber": 3,
      "poNumber": 100000000,
      "quantity": 0.33
    }
  ]
}
"""


_EMPTY_RESPONSE: Final[str] = (
    '{"statusCode": 200, "totalCount": 0, "message": "No data found.", "items": []}'
)


class TestLiveSampleParse:
    def test_full_sample_parses(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        assert response.status_code == 200
        assert response.total_count == 75314
        assert len(response.items) == 3
        assert response.page_info is not None
        assert response.page_info.last_change_record_id == 100000004

    def test_first_line_core_fields(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.po_number == 100000000
        assert first_line.po_details_id == 100000001
        assert first_line.po_line_number == 1
        assert first_line.ata_code == '1D001004'
        assert first_line.ata_description == 'OUT OF NETWORK FEE'
        assert first_line.vendor_id == '000000XX'
        assert first_line.vin == '1XXXXXXXXXXXXXXXX'
        assert first_line.lessee_code == 'XXXX'
        assert first_line.type_ == 'O'

    def test_cost_zero_int_shaped_parses_as_float(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.cost == 0
        assert isinstance(first_line.cost, float)
        assert first_line.po_total_line_cost == 0
        assert isinstance(first_line.po_total_line_cost, float)

    def test_cost_decimal_parses_as_float(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        third_line: MaintenancePurchaseOrder = response.items[2]
        assert third_line.cost == 336.09
        assert isinstance(third_line.cost, float)
        assert third_line.po_total_line_cost == 336.09
        assert isinstance(third_line.po_total_line_cost, float)

    def test_odometer_stays_int(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.odometer == 173367
        assert isinstance(first_line.odometer, int)

    def test_int_shaped_quantity_parses_as_float(self) -> None:
        # The sample fixture's ``quantity: 1`` is a JSON integer; under
        # the new ``float | None`` typing it must still parse, just as
        # a ``float`` value of ``1.0``. Pin both the equality and the
        # type so a future regression to ``int`` typing is loud.
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.quantity == 1.0
        assert isinstance(first_line.quantity, float)

    def test_datetimes_parsed_as_utc_aware(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.po_date == datetime(2025, 7, 8, tzinfo=UTC)
        assert first_line.invoice_date == datetime(2025, 7, 8, tzinfo=UTC)
        assert first_line.repair_date == datetime(2025, 7, 8, tzinfo=UTC)
        assert first_line.bill_paid_date == datetime(2025, 7, 8, tzinfo=UTC)
        assert first_line.last_change_date == datetime(
            2026, 1, 28, 18, 6, 36, tzinfo=UTC
        )

    def test_null_fields_parse_as_none(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_line: MaintenancePurchaseOrder = response.items[0]
        assert first_line.aux_data_1 is None
        assert first_line.aux_data_14 is None
        assert first_line.aux_date_1 is None
        assert first_line.client_data_7 is None
        assert first_line.hour_meter is None
        assert first_line.client_vehicle_number is None
        assert first_line.vendor_address_line_2 is None


class TestFractionalQuantity:
    """
    Regression for a live-API failure: a 1000-page first pull of
    ``maintenance_purchase_orders`` failed with 93 Pydantic validation
    errors of the form ``Input should be a valid integer, got a number
    with a fractional part`` on the ``quantity`` field. Holman returns
    half-hour labor (``0.5``), quarter-hour (``0.25``), and finer
    decimals (``0.33``); the field is a measurement, not a count, and
    must accept both int-shaped and decimal-shaped wire values.

    Under the prior ``int | None`` typing this whole envelope would
    fail to parse — Pydantic strict-validates JSON numbers against
    declared types and rejects any value with a non-zero fractional
    part for an ``int`` field.
    """

    def test_fractional_values_parse_cleanly(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _FRACTIONAL_QUANTITY_RESPONSE
        )
        assert response.status_code == 200
        assert len(response.items) == 3
        assert [line.quantity for line in response.items] == [0.5, 0.25, 0.33]
        for line in response.items:
            assert isinstance(line.quantity, float)


class TestEmptyEnvelope:
    def test_empty_envelope_parses(self) -> None:
        response = PaginatedResponse[MaintenancePurchaseOrder].model_validate_json(
            _EMPTY_RESPONSE
        )
        assert response.status_code == 200
        assert response.total_count == 0
        assert response.items == []
        assert response.page_info is None
        assert response.message == 'No data found.'
