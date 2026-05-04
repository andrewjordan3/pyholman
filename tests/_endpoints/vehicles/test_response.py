# tests/_endpoints/vehicles/test_response.py
"""Tests for the Vehicle response model against Holman live payloads."""

import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from pyholman._core import PaginatedResponse
from pyholman._endpoints.vehicles import Vehicle

__all__: list[str] = []


_SAMPLE_PAGE_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 4744,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 5,
    "totalPages": 949,
    "lastChangeRecordId": null
  },
  "items": [
    {
      "addressLine1": "123 EXAMPLE ST",
      "addressLine2": "SUITE 100",
      "addressLine3": null,
      "assetSubtype": null,
      "assetType": "TRAILER",
      "assignedStatus": null,
      "auxData1": "DATA1",
      "auxData10": null,
      "auxData11": null,
      "auxData12": null,
      "auxData13": null,
      "auxData14": null,
      "auxData2": "DATA2",
      "auxData3": null,
      "auxData4": "DATA4",
      "auxData5": null,
      "auxData6": null,
      "auxData7": null,
      "auxData8": "DATA8",
      "auxData9": null,
      "auxDate1": null,
      "auxDate2": null,
      "auxDate3": null,
      "auxDate4": null,
      "capCost": "106171.2",
      "cellPhone": "5555550100",
      "city": "EXAMPLE CITY",
      "clientData1": "DATA1",
      "clientData2": "DATA2",
      "clientData3": "DATA3",
      "clientData4": "DATA4",
      "clientData5": "DATA5",
      "clientData6": "DATA6",
      "clientData7": "DATA7",
      "clientVehicleNumber": "888880",
      "curbWeight": "000000",
      "deliveryDate": "2008-03-28T00:00:00Z",
      "division": "05",
      "driveline": null,
      "driverClass": "S",
      "email": "user1@example.com",
      "engineType": null,
      "exec": "L",
      "firstName": "FIRSTNAME1",
      "fuelCapacity": 0,
      "fuelMeasureType": "G",
      "fuelType": null,
      "fuelTypeCode": "01",
      "fuelTypeDescription": "Diesel",
      "gvwr": 80000,
      "holmanVehicleNumber": "999990",
      "homePhone": null,
      "hourMeter": null,
      "hourMeterDate": null,
      "lastChangeDate": "2026-04-14T07:52:01Z",
      "lastChangeRecordId": 100000010,
      "lastName": "LASTNAME1",
      "leaseEndDate": "2014-03-31T00:00:00Z",
      "leaseStartDate": "2008-04-01T00:00:00Z",
      "leaseTerm": "72",
      "lesseeCode": "XXXX",
      "licensePlate": "XXX0000",
      "makeClient": "PRESVAC",
      "makeVin": "PRESVAC",
      "modelClient": "VACUUM TANK TRAILER",
      "modelVin": "VACUUM TANK TRAILER",
      "modelYear": "2008",
      "monthsBilled": 218,
      "monthsInService": 216,
      "odometer": "1001",
      "odometerDate": "2026-04-19T01:00:00Z",
      "onRoadDate": null,
      "orderType": "D",
      "outOfServiceDate": null,
      "plateType": "TRL",
      "prefix": null,
      "registeredVehicleWeight": "000000",
      "remainingBookValue": 0,
      "renewalDate": "2027-12-31T00:00:00Z",
      "saleOdometer": 0,
      "series": null,
      "soldAmount": 0,
      "soldDate": null,
      "stateProvince": "XX",
      "status": "Active",
      "statusCode": 1,
      "tagStateProvince": "XX",
      "telematicsDeviceId": null,
      "telematicsDeviceModel": null,
      "telematicsDeviceVendor": null,
      "titleLocationDescription": "IN-HOUSE",
      "titleOwnerLessor": "ARI FLEET LT",
      "vendor": "ARI",
      "vin": "1XXXXXXXXXXXXXX10",
      "workPhone": "5555550101",
      "workPhoneExtension": null,
      "zipPostalCode": "00000"
    },
    {
      "addressLine1": "EXAMPLE COMPANY",
      "addressLine2": "456 EXAMPLE AVE",
      "addressLine3": null,
      "assetSubtype": null,
      "assetType": "CAR",
      "assignedStatus": null,
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
      "capCost": "16361.38",
      "cellPhone": null,
      "city": "EXAMPLE CITY 2",
      "clientData1": "DATA1",
      "clientData2": null,
      "clientData3": "DATA3",
      "clientData4": "DATA4",
      "clientData5": "DATA5",
      "clientData6": null,
      "clientData7": "DATA7",
      "clientVehicleNumber": null,
      "curbWeight": "3204",
      "deliveryDate": "2008-03-12T00:00:00Z",
      "division": "WR",
      "driveline": "FWD",
      "driverClass": "S",
      "email": "user2@example.com",
      "engineType": "L4, 2.3L",
      "exec": "L",
      "firstName": "FIRSTNAME2",
      "fuelCapacity": 17.5,
      "fuelMeasureType": "G",
      "fuelType": "00",
      "fuelTypeCode": "00",
      "fuelTypeDescription": "Gas",
      "gvwr": 0,
      "holmanVehicleNumber": "999991",
      "homePhone": null,
      "hourMeter": null,
      "hourMeterDate": null,
      "lastChangeDate": null,
      "lastChangeRecordId": null,
      "lastName": "LASTNAME2",
      "leaseEndDate": "2013-02-28T00:00:00Z",
      "leaseStartDate": "2008-03-01T00:00:00Z",
      "leaseTerm": "60",
      "lesseeCode": "XXXX",
      "licensePlate": "XXX0001",
      "makeClient": "MERCURY",
      "makeVin": "MERCURY",
      "modelClient": "MILAN",
      "modelVin": "MILAN",
      "modelYear": "2008",
      "monthsBilled": 57,
      "monthsInService": 57,
      "odometer": "140201",
      "odometerDate": "2012-12-07T10:38:10Z",
      "onRoadDate": null,
      "orderType": "F",
      "outOfServiceDate": "2012-12-13T00:00:00Z",
      "plateType": "PAS",
      "prefix": null,
      "registeredVehicleWeight": "003300",
      "remainingBookValue": 905.84,
      "renewalDate": "2013-02-28T00:00:00Z",
      "saleOdometer": 140426,
      "series": null,
      "soldAmount": 4170,
      "soldDate": "2012-12-27T00:00:00Z",
      "stateProvince": "XX",
      "status": "Sold Previous Year",
      "statusCode": 4,
      "tagStateProvince": "XX",
      "telematicsDeviceId": null,
      "telematicsDeviceModel": null,
      "telematicsDeviceVendor": null,
      "titleLocationDescription": "USED VEHICLE",
      "titleOwnerLessor": "Ari Trust",
      "vendor": "ARI",
      "vin": "1XXXXXXXXXXXXXX11",
      "workPhone": "5555550102",
      "workPhoneExtension": null,
      "zipPostalCode": "00001"
    }
  ]
}
"""

_EMPTY_RESPONSE: Final[str] = (
    '{"statusCode": 200, "totalCount": 0, "message": "No data found.", "items": []}'
)


class TestLiveSampleParse:
    def test_full_sample_parses(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 4744
        assert len(response.items) == 2
        assert response.page_info is not None
        assert response.page_info.page_number == 1
        assert response.page_info.total_pages == 949

    def test_page_info_last_change_record_id_null_parses(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        assert response.page_info is not None
        assert response.page_info.last_change_record_id is None

    def test_active_vehicle_core_fields(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.holman_vehicle_number == '999990'
        assert active_vehicle.vin == '1XXXXXXXXXXXXXX10'
        assert active_vehicle.status == 'Active'
        assert active_vehicle.status_code == 1
        assert active_vehicle.asset_type == 'TRAILER'

    def test_codes_with_leading_zeros_stay_strings(self) -> None:
        # Code-shaped fields (division, fuelTypeCode) keep the wire's
        # leading zeros — the padding distinguishes ``"01"`` from
        # ``"1"`` in Holman's reference lists.
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.division == '05'
        assert active_vehicle.fuel_type_code == '01'

    def test_zero_padded_weights_coerce_to_zero(self) -> None:
        # ``curbWeight='000000'`` and ``registeredVehicleWeight='000000'``
        # are Holman's empty-state convention for the weight fields, the
        # same shape ``gvwr=0`` carries on the wire as a real int. The
        # field validators coerce to int so the empty state is unambiguous.
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.curb_weight == 0
        assert active_vehicle.registered_vehicle_weight == 0
        assert isinstance(active_vehicle.curb_weight, int)
        assert isinstance(active_vehicle.registered_vehicle_weight, int)

    def test_coerced_numeric_fields_are_numeric(self) -> None:
        # Six fields that arrive as quoted-numeric strings on the wire
        # are coerced to their proper numeric types by ``mode='before'``
        # validators. Active vehicle has typical values; the second
        # record exercises the same pattern with non-zero weights.
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        sold_vehicle: Vehicle = response.items[1]

        assert active_vehicle.cap_cost == 106171.2
        assert isinstance(active_vehicle.cap_cost, float)

        assert active_vehicle.odometer == 1001
        assert isinstance(active_vehicle.odometer, int)

        assert active_vehicle.lease_term == 72
        assert active_vehicle.model_year == 2008
        assert isinstance(active_vehicle.lease_term, int)
        assert isinstance(active_vehicle.model_year, int)

        assert sold_vehicle.cap_cost == 16361.38
        assert sold_vehicle.curb_weight == 3204
        assert sold_vehicle.registered_vehicle_weight == 3300
        assert sold_vehicle.odometer == 140201

    def test_numeric_fields_typed_correctly(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.gvwr == 80000
        assert active_vehicle.months_billed == 218
        assert active_vehicle.months_in_service == 216
        assert active_vehicle.last_change_record_id == 100000010
        assert isinstance(active_vehicle.gvwr, int)
        assert isinstance(active_vehicle.last_change_record_id, int)

    def test_sold_vehicle_monetary_fields(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        sold_vehicle: Vehicle = response.items[1]
        assert sold_vehicle.sale_odometer == 140426
        assert sold_vehicle.sold_amount == 4170
        assert sold_vehicle.remaining_book_value == 905.84
        assert sold_vehicle.status == 'Sold Previous Year'

    def test_datetimes_parsed_as_utc_aware(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.last_change_date == datetime(
            2026, 4, 14, 7, 52, 1, tzinfo=UTC
        )
        assert active_vehicle.delivery_date == datetime(2008, 3, 28, tzinfo=UTC)

    def test_record_with_null_last_change_fields_parses(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        sold_vehicle: Vehicle = response.items[1]
        assert sold_vehicle.last_change_date is None
        assert sold_vehicle.last_change_record_id is None

    def test_null_fields_parse_as_none(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        active_vehicle: Vehicle = response.items[0]
        assert active_vehicle.address_line_3 is None
        assert active_vehicle.aux_data_10 is None
        assert active_vehicle.aux_date_1 is None
        assert active_vehicle.sold_date is None
        assert active_vehicle.out_of_service_date is None


class TestEmptyEnvelope:
    def test_empty_envelope_parses(self) -> None:
        response = PaginatedResponse[Vehicle].model_validate_json(_EMPTY_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 0
        assert response.items == []
        assert response.page_info is None
        assert response.message == 'No data found.'


class TestNumericCoercionEdgeCases:
    """
    Edge-case coverage for the six ``mode='before'`` numeric validators.

    The full-sample tests above exercise the typical wire shapes; this
    class pins the explicit ``None`` and empty-string inputs that the
    validators map to ``None``, plus the rejection path for unsupported
    input types.
    """

    def _envelope_with(self, item: dict[str, object]) -> str:
        return json.dumps(
            {
                'statusCode': 200,
                'totalCount': 1,
                'pageInfo': {
                    'pageNumber': 1,
                    'pageSize': 1,
                    'totalPages': 1,
                    'lastChangeRecordId': None,
                },
                'items': [item],
            }
        )

    def test_empty_string_coerces_to_none(self) -> None:
        # Some Holman endpoints return empty strings instead of JSON
        # ``null`` for missing values; the coerce-from-string validators
        # absorb that into ``None`` so the empty-state is unambiguous.
        envelope: str = self._envelope_with(
            {'capCost': '', 'odometer': '', 'modelYear': ''}
        )
        response = PaginatedResponse[Vehicle].model_validate_json(envelope)
        record: Vehicle = response.items[0]
        assert record.cap_cost is None
        assert record.odometer is None
        assert record.model_year is None

    def test_non_numeric_string_raises(self) -> None:
        envelope: str = self._envelope_with({'odometer': 'not-a-number'})
        with pytest.raises(ValidationError):
            PaginatedResponse[Vehicle].model_validate_json(envelope)

    def test_unsupported_input_type_raises(self) -> None:
        # Direct construction (not from JSON) lets us pass a dict to a
        # numeric field; the validator should reject with a ValidationError
        # whose message names the field.
        with pytest.raises(ValidationError, match='odometer'):
            Vehicle(odometer={'not': 'numeric'})  # type: ignore[arg-type]


class TestWhitespaceStripping:
    """
    End-to-end coverage that ``ResponseModel``'s base-class strip runs on
    Vehicle records. Holman's live data ships VINs with leading
    whitespace; the base validator normalizes before field parsing.
    """

    @staticmethod
    def _envelope_with(item: dict[str, object]) -> str:
        return json.dumps(
            {
                'statusCode': 200,
                'totalCount': 1,
                'pageInfo': {
                    'pageNumber': 1,
                    'pageSize': 1,
                    'totalPages': 1,
                    'lastChangeRecordId': None,
                },
                'items': [item],
            }
        )

    def test_vin_with_leading_whitespace_strips(self) -> None:
        # VIN field arrives with leading whitespace and must round-trip
        # stripped. Synthetic placeholder mirrors the wire shape.
        envelope: str = self._envelope_with({'vin': '            XXXXX'})
        response = PaginatedResponse[Vehicle].model_validate_json(envelope)
        assert response.items[0].vin == 'XXXXX'

    def test_zero_padded_vin_preserved(self) -> None:
        # The base validator strips whitespace, not numeric padding;
        # interior zeros must survive.
        envelope: str = self._envelope_with({'vin': '00000000000000000'})
        response = PaginatedResponse[Vehicle].model_validate_json(envelope)
        assert response.items[0].vin == '00000000000000000'
