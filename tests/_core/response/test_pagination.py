# tests/_core/response/test_pagination.py
"""Tests for the pagination envelope (PageInfo, PaginatedResponse)."""

from typing import Any

import pytest
from pydantic import Field, ValidationError

from pyholman._core import PageInfo, PaginatedResponse, ResponseModel

__all__: list[str] = []


class _TestItem(ResponseModel):
    """Minimal response-model item used as the generic parameter below."""

    item_id: int = Field(alias='itemId')
    label: str


_FULL_ENVELOPE_JSON: dict[str, Any] = {
    'statusCode': 200,
    'totalCount': 4744,
    'pageInfo': {
        'pageNumber': 1,
        'pageSize': 5,
        'totalPages': 949,
        'lastChangeRecordId': None,
    },
    'items': [
        {'itemId': 1, 'label': 'alpha'},
        {'itemId': 2, 'label': 'beta'},
    ],
}

_EMPTY_ENVELOPE_JSON: dict[str, Any] = {
    'statusCode': 200,
    'totalCount': 0,
    'message': 'No data found.',
    'items': [],
}


class TestPaginatedResponse:
    def test_full_envelope_parses(self) -> None:
        response: PaginatedResponse[_TestItem] = PaginatedResponse[
            _TestItem
        ].model_validate(_FULL_ENVELOPE_JSON)

        assert response.status_code == 200
        assert response.total_count == 4744
        assert response.page_info is not None
        assert response.page_info.page_number == 1
        assert response.page_info.page_size == 5
        assert response.page_info.total_pages == 949
        assert response.page_info.last_change_record_id is None
        assert len(response.items) == 2
        assert response.items[0].item_id == 1
        assert response.items[0].label == 'alpha'
        assert response.message is None

    def test_empty_envelope_parses(self) -> None:
        response: PaginatedResponse[_TestItem] = PaginatedResponse[
            _TestItem
        ].model_validate(_EMPTY_ENVELOPE_JSON)

        assert response.status_code == 200
        assert response.total_count == 0
        assert response.page_info is None
        assert response.items == []
        assert response.message == 'No data found.'

    def test_past_end_pagination_matches_empty_shape(self) -> None:
        # Past-end pages come back with the same shape as an empty
        # response — the iterator stops when ``items`` is empty.
        past_end_json: dict[str, Any] = {
            'statusCode': 200,
            'totalCount': 0,
            'message': 'No data found.',
            'items': [],
        }
        response: PaginatedResponse[_TestItem] = PaginatedResponse[
            _TestItem
        ].model_validate(past_end_json)

        assert response.items == []
        assert response.page_info is None

    def test_generic_items_typed_as_item_class(self) -> None:
        response: PaginatedResponse[_TestItem] = PaginatedResponse[
            _TestItem
        ].model_validate(_FULL_ENVELOPE_JSON)
        for item in response.items:
            assert isinstance(item, _TestItem)

    def test_extra_envelope_fields_silently_dropped(self) -> None:
        envelope_with_extras: dict[str, Any] = {
            **_EMPTY_ENVELOPE_JSON,
            'unexpectedKey': 'surprise',
            'extra_snake': 42,
        }
        response: PaginatedResponse[_TestItem] = PaginatedResponse[
            _TestItem
        ].model_validate(envelope_with_extras)
        assert response.total_count == 0
        assert not hasattr(response, 'unexpectedKey')
        assert not hasattr(response, 'extra_snake')


class TestPageInfo:
    def test_total_pages_zero_accepted(self) -> None:
        page_info: PageInfo = PageInfo(
            pageNumber=1,  # type: ignore[call-arg]
            pageSize=1,  # type: ignore[call-arg]
            totalPages=0,  # type: ignore[call-arg]
        )
        assert page_info.total_pages == 0

    def test_last_change_record_id_none_accepted(self) -> None:
        page_info: PageInfo = PageInfo(
            pageNumber=1,  # type: ignore[call-arg]
            pageSize=1,  # type: ignore[call-arg]
            totalPages=1,  # type: ignore[call-arg]
            lastChangeRecordId=None,  # type: ignore[call-arg]
        )
        assert page_info.last_change_record_id is None

    def test_last_change_record_id_populated(self) -> None:
        page_info: PageInfo = PageInfo(
            pageNumber=1,  # type: ignore[call-arg]
            pageSize=1,  # type: ignore[call-arg]
            totalPages=1,  # type: ignore[call-arg]
            lastChangeRecordId=12345,  # type: ignore[call-arg]
        )
        assert page_info.last_change_record_id == 12345

    @pytest.mark.parametrize(
        ('field_name', 'invalid_value'),
        [
            ('pageNumber', 0),
            ('pageNumber', -1),
            ('pageSize', 0),
            ('pageSize', -5),
            ('totalPages', -1),
        ],
    )
    def test_negative_or_zero_values_rejected(
        self,
        field_name: str,
        invalid_value: int,
    ) -> None:
        kwargs: dict[str, Any] = {
            'pageNumber': 1,
            'pageSize': 1,
            'totalPages': 0,
        }
        kwargs[field_name] = invalid_value
        with pytest.raises(ValidationError):
            PageInfo(**kwargs)

    def test_populate_by_name_allows_snake_case_construction(self) -> None:
        # ResponseModel's populate_by_name=True lets tests construct
        # instances with Python-native names as well as JSON aliases.
        page_info: PageInfo = PageInfo(
            page_number=2,
            page_size=50,
            total_pages=3,
            last_change_record_id=7,
        )
        assert page_info.page_number == 2
        assert page_info.page_size == 50
        assert page_info.total_pages == 3
        assert page_info.last_change_record_id == 7
