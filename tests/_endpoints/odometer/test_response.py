# tests/_endpoints/odometer/test_response.py
"""Tests for the Odometer response model against live payloads."""

from datetime import UTC, datetime
from typing import Final

from pyholman._core import PaginatedResponse
from pyholman._endpoints.odometer import Odometer

__all__: list[str] = []


_SAMPLE_PAGE_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 373,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 5,
    "totalPages": 75,
    "lastChangeRecordId": 100000034
  },
  "items": [
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999992",
      "icnNo": 100000030,
      "lastChangeDate": "2026-04-23T23:34:25Z",
      "lastChangeRecordId": 100000035,
      "lesseeCode": "XXXX",
      "odometer": 32421,
      "odometerDate": "2026-04-23T23:43:14Z",
      "odometerHistoryId": 100000040,
      "odometerQuality": null,
      "odometerSource": "SMSR",
      "prefix": null,
      "vehicleId": 100000050,
      "vin": "1XXXXXXXXXXXXXX30"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999993",
      "icnNo": 100000031,
      "lastChangeDate": "2026-04-23T18:42:35Z",
      "lastChangeRecordId": 100000036,
      "lesseeCode": "XXXX",
      "odometer": 98776,
      "odometerDate": "2026-04-23T19:18:31Z",
      "odometerHistoryId": 100000041,
      "odometerQuality": null,
      "odometerSource": "SMSR",
      "prefix": null,
      "vehicleId": 100000051,
      "vin": "1XXXXXXXXXXXXXX31"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999994",
      "icnNo": 100000032,
      "lastChangeDate": "2026-04-23T23:23:03Z",
      "lastChangeRecordId": 100000037,
      "lesseeCode": "XXXX",
      "odometer": 76398,
      "odometerDate": "2026-04-23T23:45:02Z",
      "odometerHistoryId": 100000042,
      "odometerQuality": null,
      "odometerSource": "SMSR",
      "prefix": null,
      "vehicleId": 100000052,
      "vin": "1XXXXXXXXXXXXXX32"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999995",
      "icnNo": 100000033,
      "lastChangeDate": "2026-04-23T23:23:04Z",
      "lastChangeRecordId": 100000038,
      "lesseeCode": "XXXX",
      "odometer": 163688,
      "odometerDate": "2026-04-23T23:18:53Z",
      "odometerHistoryId": 100000043,
      "odometerQuality": null,
      "odometerSource": "SMSR",
      "prefix": null,
      "vehicleId": 100000053,
      "vin": "1XXXXXXXXXXXXXX33"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999996",
      "icnNo": 100000039,
      "lastChangeDate": "2026-04-23T23:23:04Z",
      "lastChangeRecordId": 100000034,
      "lesseeCode": "XXXX",
      "odometer": 124358,
      "odometerDate": "2026-04-23T23:38:22Z",
      "odometerHistoryId": 100000044,
      "odometerQuality": null,
      "odometerSource": "SMSR",
      "prefix": null,
      "vehicleId": 100000054,
      "vin": "1XXXXXXXXXXXXXX34"
    }
  ]
}
"""

_EMPTY_RESPONSE: Final[str] = (
    '{"statusCode": 200, "totalCount": 0, "message": "No data found.", "items": []}'
)


class TestLiveSampleParse:
    def test_full_sample_parses(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        assert response.status_code == 200
        assert response.total_count == 373
        assert len(response.items) == 5

    def test_page_info_last_change_record_id_populated(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        assert response.page_info is not None
        assert response.page_info.last_change_record_id == 100000034
        assert isinstance(response.page_info.last_change_record_id, int)

    def test_numeric_fields_stay_int(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: Odometer = response.items[0]
        assert first_record.odometer == 32421
        assert first_record.icn_no == 100000030
        assert first_record.odometer_history_id == 100000040
        assert first_record.vehicle_id == 100000050
        assert first_record.last_change_record_id == 100000035
        assert isinstance(first_record.odometer, int)
        assert isinstance(first_record.icn_no, int)
        assert isinstance(first_record.odometer_history_id, int)
        assert isinstance(first_record.vehicle_id, int)
        assert isinstance(first_record.last_change_record_id, int)

    def test_string_fields_stay_str(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: Odometer = response.items[0]
        assert first_record.holman_vehicle_number == '999992'
        assert first_record.division == '13'
        assert first_record.lessee_code == 'XXXX'
        assert first_record.odometer_source == 'SMSR'
        assert first_record.vin == '1XXXXXXXXXXXXXX30'

    def test_datetimes_parsed_as_utc_aware(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: Odometer = response.items[0]
        assert first_record.last_change_date == datetime(
            2026, 4, 23, 23, 34, 25, tzinfo=UTC
        )
        assert first_record.odometer_date == datetime(
            2026, 4, 23, 23, 43, 14, tzinfo=UTC
        )

    def test_null_fields_round_trip_as_none(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        for record in response.items:
            assert record.client_vehicle_number is None
            assert record.prefix is None
            assert record.odometer_quality is None


class TestEmptyEnvelope:
    def test_empty_envelope_parses(self) -> None:
        response = PaginatedResponse[Odometer].model_validate_json(_EMPTY_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 0
        assert response.items == []
        assert response.page_info is None
        assert response.message == 'No data found.'
