# tests/_endpoints/contacts/test_response.py
"""Tests for the Contact response model against live payloads."""

import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from pyholman._core import PaginatedResponse
from pyholman._endpoints.contacts import Contact

__all__: list[str] = []


_SAMPLE_PAGE_RESPONSE: Final[str] = """
{
  "statusCode": 200,
  "totalCount": 3860,
  "pageInfo": {
    "pageNumber": 1,
    "pageSize": 5,
    "totalPages": 772,
    "lastChangeRecordId": 100000020
  },
  "items": [
    {
      "city": null,
      "contactActivationDate": "2026-01-30T10:45:33Z",
      "contactAddress1": null,
      "contactAddress2": null,
      "contactAddress3": null,
      "contactAuxData1": "DATA1",
      "contactAuxData10": null,
      "contactAuxData11": null,
      "contactAuxData12": null,
      "contactAuxData13": null,
      "contactAuxData14": null,
      "contactAuxData2": null,
      "contactAuxData3": null,
      "contactAuxData4": null,
      "contactAuxData5": null,
      "contactAuxData6": null,
      "contactAuxData7": null,
      "contactAuxData8": null,
      "contactAuxData9": null,
      "contactAuxDate1": null,
      "contactAuxDate2": null,
      "contactAuxDate3": null,
      "contactAuxDate4": null,
      "contactCellAcceptsText": "N",
      "contactCellPhone": "5555550110",
      "contactData1": null,
      "contactData3": null,
      "contactData4": null,
      "contactData5": null,
      "contactData6": null,
      "contactData7": null,
      "contactDeactivationDate": null,
      "contactEmail": "user1@example.com",
      "contactEmployeeId": "EMP00001",
      "contactFirstName": "FIRSTNAME1",
      "contactHireDate": null,
      "contactHomePhone": null,
      "contactLastName": "LASTNAME1",
      "contactMiddleName": null,
      "contactStatus": "ACTIVATED",
      "contactTerminationDate": null,
      "contactWorkPhone": null,
      "contactWorkPhoneExtension": null,
      "country": null,
      "county": null,
      "languagePreference": "en-US",
      "lastChangeDate": "2026-01-30T10:45:33Z",
      "lastChangeRecordId": 100000020,
      "stateProvince": null,
      "supervisorEmail": null,
      "zipPostalCode": null
    },
    {
      "city": null,
      "contactActivationDate": "2026-01-30T10:45:33Z",
      "contactAddress1": null,
      "contactAddress2": null,
      "contactAddress3": null,
      "contactAuxData1": "DATA1B",
      "contactAuxData10": null,
      "contactAuxData11": null,
      "contactAuxData12": null,
      "contactAuxData13": null,
      "contactAuxData14": null,
      "contactAuxData2": null,
      "contactAuxData3": null,
      "contactAuxData4": null,
      "contactAuxData5": null,
      "contactAuxData6": null,
      "contactAuxData7": null,
      "contactAuxData8": null,
      "contactAuxData9": null,
      "contactAuxDate1": null,
      "contactAuxDate2": null,
      "contactAuxDate3": null,
      "contactAuxDate4": null,
      "contactCellAcceptsText": "N",
      "contactCellPhone": "5555550111",
      "contactData1": null,
      "contactData3": null,
      "contactData4": null,
      "contactData5": null,
      "contactData6": null,
      "contactData7": null,
      "contactDeactivationDate": null,
      "contactEmail": "user2@example.com",
      "contactEmployeeId": "EMP00002",
      "contactFirstName": "FIRSTNAME2",
      "contactHireDate": null,
      "contactHomePhone": null,
      "contactLastName": "LASTNAME2",
      "contactMiddleName": null,
      "contactStatus": "ACTIVATED",
      "contactTerminationDate": null,
      "contactWorkPhone": null,
      "contactWorkPhoneExtension": null,
      "country": null,
      "county": null,
      "languagePreference": "en-US",
      "lastChangeDate": "2026-01-30T10:45:33Z",
      "lastChangeRecordId": 100000021,
      "stateProvince": null,
      "supervisorEmail": null,
      "zipPostalCode": null
    }
  ]
}
"""

_EMPTY_RESPONSE: Final[str] = (
    '{"statusCode": 200, "totalCount": 0, "message": "No data found.", "items": []}'
)


class TestLiveSampleParse:
    def test_full_sample_parses(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 3860
        assert len(response.items) == 2

    def test_page_info_last_change_record_id_populated(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        assert response.page_info is not None
        assert response.page_info.last_change_record_id == 100000020

    def test_prefix_stripped_names_map_to_aliases(self) -> None:
        # Regression guard for the prefix-stripping rule: verifies that
        # the Python-side names without the ``contact_`` prefix still
        # resolve their values through Holman's literal ``contact*``
        # wire aliases.
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        first_record: Contact = response.items[0]
        assert first_record.first_name == 'FIRSTNAME1'
        assert first_record.last_name == 'LASTNAME1'
        assert first_record.email == 'user1@example.com'
        assert first_record.employee_id == 'EMP00001'
        assert first_record.cell_phone == '5555550110'
        assert first_record.cell_accepts_text is False
        assert first_record.status == 'ACTIVATED'
        assert first_record.aux_data_1 == 'DATA1'

    def test_unprefixed_wire_fields_parse(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        first_record: Contact = response.items[0]
        assert first_record.language_preference == 'en-US'
        assert first_record.last_change_record_id == 100000020

    def test_activation_date_parsed_as_utc_aware(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        first_record: Contact = response.items[0]
        assert first_record.activation_date == datetime(
            2026, 1, 30, 10, 45, 33, tzinfo=UTC
        )
        assert first_record.last_change_date == datetime(
            2026, 1, 30, 10, 45, 33, tzinfo=UTC
        )

    def test_null_fields_round_trip_as_none(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        first_record: Contact = response.items[0]
        assert first_record.address_1 is None
        assert first_record.middle_name is None
        assert first_record.hire_date is None
        assert first_record.deactivation_date is None
        assert first_record.termination_date is None
        assert first_record.city is None
        assert first_record.state_province is None
        assert first_record.zip_postal_code is None
        assert first_record.aux_date_1 is None

    def test_second_record_distinct_values(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_SAMPLE_PAGE_RESPONSE)
        second_record: Contact = response.items[1]
        assert second_record.first_name == 'FIRSTNAME2'
        assert second_record.last_name == 'LASTNAME2'
        assert second_record.cell_phone == '5555550111'
        assert second_record.aux_data_1 == 'DATA1B'
        assert second_record.last_change_record_id == 100000021


class TestDataTwoRegressionGuard:
    def test_contact_data_2_round_trips_when_present(self) -> None:
        # ``contactData2`` is modeled on the PDF's authority even though
        # Andrew's sample responses never populated it. If Holman ever
        # starts sending the field, Pydantic's ``extra='ignore'`` would
        # silently drop an unmodeled slot — this synthetic payload locks
        # in the declared field so that drop can't happen.
        synthetic_record: dict[str, object] = {
            'contactData1': None,
            'contactData2': 'populated-value',
            'contactData3': None,
            'contactData4': None,
            'contactData5': None,
            'contactData6': None,
            'contactData7': None,
        }
        synthetic_envelope: str = json.dumps(
            {
                'statusCode': 200,
                'totalCount': 1,
                'pageInfo': {
                    'pageNumber': 1,
                    'pageSize': 1,
                    'totalPages': 1,
                    'lastChangeRecordId': None,
                },
                'items': [synthetic_record],
            }
        )
        response = PaginatedResponse[Contact].model_validate_json(synthetic_envelope)
        parsed_record: Contact = response.items[0]
        assert parsed_record.data_1 is None
        assert parsed_record.data_2 == 'populated-value'
        assert parsed_record.data_3 is None


class TestEmptyEnvelope:
    def test_empty_envelope_parses(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(_EMPTY_RESPONSE)
        assert response.status_code == 200
        assert response.total_count == 0
        assert response.items == []
        assert response.page_info is None
        assert response.message == 'No data found.'


class TestCellAcceptsTextCoercion:
    """Coverage for the Y/N → ``bool`` validator on ``cell_accepts_text``."""

    @staticmethod
    def _envelope_with(value: object) -> str:
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
                'items': [{'contactCellAcceptsText': value}],
            }
        )

    def test_yes_indicator_coerces_to_true(self) -> None:
        # The synthetic live sample only carries ``"N"``; the ``"Y"``
        # path needs explicit coverage.
        response = PaginatedResponse[Contact].model_validate_json(
            self._envelope_with('Y'),
        )
        assert response.items[0].cell_accepts_text is True

    def test_empty_string_coerces_to_none(self) -> None:
        response = PaginatedResponse[Contact].model_validate_json(
            self._envelope_with(''),
        )
        assert response.items[0].cell_accepts_text is None

    def test_unrecognized_value_raises(self) -> None:
        with pytest.raises(ValidationError, match='cell_accepts_text'):
            PaginatedResponse[Contact].model_validate_json(
                self._envelope_with('X'),
            )
