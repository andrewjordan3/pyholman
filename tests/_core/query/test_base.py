# tests/_core/query/test_base.py
"""Tests for the QueryInputBase dataclass."""

from dataclasses import FrozenInstanceError, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._core.query.base import _serialize_query_value

__all__: list[str] = []


class _TestItem(ResponseModel):
    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _TestQuery(QueryInputBase[_TestItem]):
    endpoint_path: ClassVar[str] = '/CustomerDataAPI/test/basic-query'
    response_item_type: ClassVar[type[ResponseModel]] = _TestItem

    extra_filter: str | None = field(
        default=None,
        metadata={'api_key': 'extraFilter'},
    )
    include_archived: bool = field(
        default=False,
        metadata={'api_key': 'includeArchived'},
    )


_DEFAULT_BASE_URL: str = 'https://api.holman.solutions'
_DEFAULT_PAGE_NUMBER: int = 1
_DEFAULT_PAGE_SIZE: int = 200


def _default_query(**overrides: object) -> _TestQuery:
    """Build a ``_TestQuery`` with sensible defaults for reuse across tests."""
    construction_kwargs: dict[str, object] = {
        'base_url': _DEFAULT_BASE_URL,
        'lessee_codes': ('AAAA',),
    }
    construction_kwargs.update(overrides)
    return _TestQuery(**construction_kwargs)  # type: ignore[arg-type]


class TestSubclassContract:
    def test_missing_endpoint_path_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match='endpoint_path'):

            @dataclass(frozen=True, slots=True, kw_only=True)
            class _NoEndpoint(QueryInputBase[_TestItem]):  # pragma: no cover
                response_item_type: ClassVar[type[ResponseModel]] = _TestItem

    def test_missing_response_item_type_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match='response_item_type'):

            @dataclass(frozen=True, slots=True, kw_only=True)
            class _NoItemType(QueryInputBase[_TestItem]):  # pragma: no cover
                endpoint_path: ClassVar[str] = '/p'


class TestInstanceProperties:
    def test_frozen_instance_cannot_be_mutated(self) -> None:
        query: _TestQuery = _default_query()
        with pytest.raises(FrozenInstanceError):
            query.base_url = 'https://other.example.com'  # type: ignore[misc]

    def test_slots_leave_no_dict(self) -> None:
        query: _TestQuery = _default_query()
        assert not hasattr(query, '__dict__')

    def test_pagination_fields_not_on_instance(self) -> None:
        # Pagination is a transport concern, not a query-input concern —
        # the fields were removed from the dataclass and must stay off.
        query: _TestQuery = _default_query()
        assert not hasattr(query, 'page_size')
        assert not hasattr(query, 'page_number')


class TestUrl:
    def test_url_composes_base_path_and_query_params(self) -> None:
        query: _TestQuery = _default_query()
        full_url: str = query.url(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )

        parsed_url = urlsplit(full_url)
        assert parsed_url.scheme == 'https'
        assert parsed_url.netloc == 'api.holman.solutions'
        assert parsed_url.path == '/CustomerDataAPI/test/basic-query'

        parsed_query: dict[str, list[str]] = parse_qs(parsed_url.query)
        assert parsed_query['lesseeCodes'] == ['AAAA']
        assert parsed_query['pageSize'] == [str(_DEFAULT_PAGE_SIZE)]
        assert parsed_query['pageNumber'] == [str(_DEFAULT_PAGE_NUMBER)]
        assert parsed_query['includeArchived'] == ['false']

    def test_url_reflects_caller_supplied_pagination(self) -> None:
        query: _TestQuery = _default_query()
        full_url: str = query.url(page_number=3, page_size=50)

        parsed_query: dict[str, list[str]] = parse_qs(urlsplit(full_url).query)
        assert parsed_query['pageNumber'] == ['3']
        assert parsed_query['pageSize'] == ['50']


class TestQueryParams:
    def test_required_only_construction_emits_expected_keys(self) -> None:
        query: _TestQuery = _default_query()
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )

        assert params == {
            'lesseeCodes': 'AAAA',
            'pageSize': str(_DEFAULT_PAGE_SIZE),
            'pageNumber': str(_DEFAULT_PAGE_NUMBER),
            'includeArchived': 'false',
        }

    def test_pagination_values_pass_through_unchanged(self) -> None:
        query: _TestQuery = _default_query()
        params: dict[str, str] = query.query_params(page_number=7, page_size=500)
        assert params['pageNumber'] == '7'
        assert params['pageSize'] == '500'

    def test_lessee_codes_serialize_as_comma_joined(self) -> None:
        query: _TestQuery = _default_query(lessee_codes=('AAAA', 'XXXX'))
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['lesseeCodes'] == 'AAAA,XXXX'

    def test_last_change_date_serializes_utc_iso_with_z_suffix(self) -> None:
        query: _TestQuery = _default_query(
            last_change_date=datetime(2026, 2, 8, tzinfo=UTC),
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['lastChangeDate'] == '2026-02-08T00:00:00.000Z'

    def test_extra_filter_string_passes_through(self) -> None:
        query: _TestQuery = _default_query(extra_filter='abc')
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['extraFilter'] == 'abc'

    def test_none_valued_fields_omitted(self) -> None:
        query: _TestQuery = _default_query(extra_filter=None)
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert 'extraFilter' not in params
        assert 'lastChangeRecordId' not in params
        assert 'lastChangeDate' not in params

    def test_include_archived_true_serializes_lowercase(self) -> None:
        query: _TestQuery = _default_query(include_archived=True)
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['includeArchived'] == 'true'

    def test_include_archived_false_serializes_lowercase(self) -> None:
        query: _TestQuery = _default_query(include_archived=False)
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['includeArchived'] == 'false'

    def test_base_url_never_appears_in_query_params(self) -> None:
        query: _TestQuery = _default_query()
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert 'base_url' not in params
        assert 'baseUrl' not in params
        for value in params.values():
            assert _DEFAULT_BASE_URL not in value

    def test_last_change_record_id_integer_serializes_as_string(self) -> None:
        query: _TestQuery = _default_query(last_change_record_id=12345)
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER,
            page_size=_DEFAULT_PAGE_SIZE,
        )
        assert params['lastChangeRecordId'] == '12345'


class TestHeaders:
    def test_headers_return_accept_json(self) -> None:
        query: _TestQuery = _default_query()
        assert query.headers() == {'Accept': 'application/json'}


class TestSerializeQueryValue:
    def test_naive_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match='timezone-aware'):
            _serialize_query_value(datetime(2026, 2, 8))  # noqa: DTZ001 -- naive is under test

    def test_non_utc_datetime_raises(self) -> None:
        eastern_offset: timezone = timezone(timedelta(hours=-5))
        with pytest.raises(ValueError, match='UTC'):
            _serialize_query_value(datetime(2026, 2, 8, tzinfo=eastern_offset))

    def test_list_serializes_as_comma_joined(self) -> None:
        assert _serialize_query_value([1, 2, 3]) == '1,2,3'

    def test_tuple_serializes_as_comma_joined(self) -> None:
        assert _serialize_query_value(('a', 'b')) == 'a,b'

    def test_fallback_to_str_for_scalars(self) -> None:
        assert _serialize_query_value(42) == '42'

    @pytest.mark.parametrize(
        ('microsecond', 'expected_fractional'),
        [
            (0, '.000Z'),
            (999, '.000Z'),
            (1000, '.001Z'),
            (123456, '.123Z'),
            (999999, '.999Z'),
        ],
    )
    def test_datetime_serializes_with_truncated_millisecond_precision(
        self, microsecond: int, expected_fractional: str
    ) -> None:
        value: datetime = datetime(
            2026, 2, 8, 14, 30, 45, microsecond=microsecond, tzinfo=UTC
        )
        assert (
            _serialize_query_value(value) == f'2026-02-08T14:30:45{expected_fractional}'
        )
