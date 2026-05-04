# tests/_endpoints/engine_hours/test_response.py
"""Tests for the EngineHours response model against live payloads."""

from datetime import UTC, datetime
from typing import Final

from pyholman._core import PaginatedResponse
from pyholman._endpoints.engine_hours import EngineHours

__all__: list[str] = []


_SAMPLE_PAGE_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 735,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 5,
    "totalPages": 147,
    "lastChangeRecordId": 100000048
  },
  "items": [
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999992",
      "hourmeter": 2934,
      "hourmeterDate": "2026-04-23T03:09:36Z",
      "hourMeterHistoryId": 100000060,
      "hourmeterSource": "SMSR",
      "icnNo": 100000030,
      "lastChangeDate": "2026-04-23T07:15:32Z",
      "lastChangeRecordId": 100000045,
      "lesseeCode": "XXXX",
      "prefix": null,
      "vehicleId": 100000050,
      "vin": "1XXXXXXXXXXXXXX30"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999992",
      "hourmeter": 2940,
      "hourmeterDate": "2026-04-24T03:09:17Z",
      "hourMeterHistoryId": 100000061,
      "hourmeterSource": "SMSR",
      "icnNo": 100000030,
      "lastChangeDate": "2026-04-24T07:11:03Z",
      "lastChangeRecordId": 100000046,
      "lesseeCode": "XXXX",
      "prefix": null,
      "vehicleId": 100000050,
      "vin": "1XXXXXXXXXXXXXX30"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999993",
      "hourmeter": 3549,
      "hourmeterDate": "2026-04-23T03:09:36Z",
      "hourMeterHistoryId": 100000062,
      "hourmeterSource": "SMSR",
      "icnNo": 100000031,
      "lastChangeDate": "2026-04-23T07:12:17Z",
      "lastChangeRecordId": 100000047,
      "lesseeCode": "XXXX",
      "prefix": null,
      "vehicleId": 100000051,
      "vin": "1XXXXXXXXXXXXXX31"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999993",
      "hourmeter": 3551,
      "hourmeterDate": "2026-04-24T03:09:17Z",
      "hourMeterHistoryId": 100000063,
      "hourmeterSource": "SMSR",
      "icnNo": 100000031,
      "lastChangeDate": "2026-04-24T07:08:33Z",
      "lastChangeRecordId": 100000049,
      "lesseeCode": "XXXX",
      "prefix": null,
      "vehicleId": 100000051,
      "vin": "1XXXXXXXXXXXXXX31"
    },
    {
      "clientVehicleNumber": null,
      "division": "13",
      "holmanVehicleNumber": "999994",
      "hourmeter": 4020,
      "hourmeterDate": "2026-04-23T03:09:36Z",
      "hourMeterHistoryId": 100000064,
      "hourmeterSource": "SMSR",
      "icnNo": 100000032,
      "lastChangeDate": "2026-04-23T07:12:17Z",
      "lastChangeRecordId": 100000048,
      "lesseeCode": "XXXX",
      "prefix": null,
      "vehicleId": 100000052,
      "vin": "1XXXXXXXXXXXXXX32"
    }
  ]
}
"""

_EMPTY_RESPONSE: Final[str] = (
    '{"statusCode": 200, "totalCount": 0, "message": "No data found.", "items": []}'
)


class TestLiveSampleParse:
    def test_full_sample_parses(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        assert response.status_code == 200
        assert response.total_count == 735
        assert len(response.items) == 5

    def test_page_info_last_change_record_id_populated(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        assert response.page_info is not None
        assert response.page_info.last_change_record_id == 100000048

    def test_mixed_casing_aliases_round_trip(self) -> None:
        # Regression guard for the four ``hour_meter*`` aliases that
        # mirror Holman's inconsistent wire casing: three lowercase
        # (``hourmeter``, ``hourmeterDate``, ``hourmeterSource``) and one
        # uppercase-M (``hourMeterHistoryId``). If any alias string
        # drifts, this test fails rather than silently dropping fields.
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: EngineHours = response.items[0]
        assert first_record.hour_meter == 2934
        assert first_record.hour_meter_date == datetime(
            2026, 4, 23, 3, 9, 36, tzinfo=UTC
        )
        assert first_record.hour_meter_source == 'SMSR'
        assert first_record.hour_meter_history_id == 100000060

    def test_numeric_fields_stay_int(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: EngineHours = response.items[0]
        assert first_record.hour_meter == 2934
        assert first_record.icn_no == 100000030
        assert first_record.hour_meter_history_id == 100000060
        assert first_record.vehicle_id == 100000050
        assert first_record.last_change_record_id == 100000045
        assert isinstance(first_record.hour_meter, int)
        assert isinstance(first_record.hour_meter_history_id, int)
        assert isinstance(first_record.icn_no, int)
        assert isinstance(first_record.vehicle_id, int)
        assert isinstance(first_record.last_change_record_id, int)

    def test_string_fields_stay_str(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: EngineHours = response.items[0]
        assert first_record.holman_vehicle_number == '999992'
        assert first_record.division == '13'
        assert first_record.lessee_code == 'XXXX'
        assert first_record.vin == '1XXXXXXXXXXXXXX30'

    def test_datetimes_parsed_as_utc_aware(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        first_record: EngineHours = response.items[0]
        assert first_record.last_change_date == datetime(
            2026, 4, 23, 7, 15, 32, tzinfo=UTC
        )
        assert first_record.hour_meter_date == datetime(
            2026, 4, 23, 3, 9, 36, tzinfo=UTC
        )

    def test_null_fields_round_trip_as_none(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(
            _SAMPLE_PAGE_RESPONSE
        )
        for record in response.items:
            assert record.client_vehicle_number is None
            assert record.prefix is None


class TestEmptyEnvelope:
    def test_empty_envelope_parses(self) -> None:
        response = PaginatedResponse[EngineHours].model_validate_json(_EMPTY_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 0
        assert response.items == []
        assert response.page_info is None
        assert response.message == 'No data found.'
