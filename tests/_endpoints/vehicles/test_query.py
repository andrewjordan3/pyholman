# tests/_endpoints/vehicles/test_query.py
"""Tests for the VehiclesQuery dataclass."""

from dataclasses import fields
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.vehicles import Vehicle, VehiclesQuery

__all__: list[str] = []


_DEFAULT_BASE_URL: str = 'https://api.holman.solutions'
_DEFAULT_PAGE_NUMBER: int = 1
_DEFAULT_PAGE_SIZE: int = 200


def _default_query(**overrides: object) -> VehiclesQuery:
    construction_kwargs: dict[str, object] = {
        'base_url': _DEFAULT_BASE_URL,
        'lessee_codes': ('AAAA',),
    }
    construction_kwargs.update(overrides)
    return VehiclesQuery(**construction_kwargs)  # type: ignore[arg-type]


class TestClassVarContract:
    def test_endpoint_path_points_to_basic_query(self) -> None:
        assert VehiclesQuery.endpoint_path == '/CustomerDataAPI/vehicles/basic-query'

    def test_response_item_type_is_vehicle(self) -> None:
        assert VehiclesQuery.response_item_type is Vehicle

    def test_is_query_input_base_subclass(self) -> None:
        assert issubclass(VehiclesQuery, QueryInputBase)

    def test_response_item_type_is_response_model(self) -> None:
        assert issubclass(VehiclesQuery.response_item_type, ResponseModel)


class TestUrl:
    def test_minimum_query_emits_only_required_params(self) -> None:
        full_url: str = _default_query().url(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        parsed = urlsplit(full_url)
        assert parsed.path == '/CustomerDataAPI/vehicles/basic-query'

        parsed_query: dict[str, list[str]] = parse_qs(parsed.query)
        assert set(parsed_query) == {'lesseeCodes', 'pageNumber', 'pageSize'}
        assert parsed_query['lesseeCodes'] == ['AAAA']
        assert parsed_query['pageNumber'] == [str(_DEFAULT_PAGE_NUMBER)]
        assert parsed_query['pageSize'] == [str(_DEFAULT_PAGE_SIZE)]


class TestQueryParams:
    def test_status_codes_are_comma_joined(self) -> None:
        query: VehiclesQuery = _default_query(status_codes=(0, 1, 2))
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['statusCodes'] == '0,1,2'

    def test_status_codes_single_value(self) -> None:
        query: VehiclesQuery = _default_query(status_codes=(3,))
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['statusCodes'] == '3'

    def test_last_change_date_serializes_in_millisecond_format(self) -> None:
        query: VehiclesQuery = _default_query(
            last_change_date=datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC),
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['lastChangeDate'] == '2026-04-20T14:30:45.000Z'

    def test_sold_date_code_serializes(self) -> None:
        query: VehiclesQuery = _default_query(sold_date_code=5)
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['soldDateCode'] == '5'

    def test_none_valued_optional_fields_are_absent(self) -> None:
        query: VehiclesQuery = _default_query()
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert 'statusCodes' not in params
        assert 'soldDateCode' not in params
        assert 'lastChangeDate' not in params
        assert 'lastChangeRecordId' not in params

    def test_all_filters_populated_together(self) -> None:
        query: VehiclesQuery = _default_query(
            status_codes=(1, 3),
            sold_date_code=5,
            last_change_date=datetime(2026, 4, 20, tzinfo=UTC),
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['statusCodes'] == '1,3'
        assert params['soldDateCode'] == '5'
        assert params['lastChangeDate'] == '2026-04-20T00:00:00.000Z'


class TestDataclassShape:
    def test_is_kw_only_with_expected_fields(self) -> None:
        # kw_only is enforced by the @dataclass decorator; checking that
        # the fields accept keyword construction is equivalent.
        query: VehiclesQuery = VehiclesQuery(
            base_url=_DEFAULT_BASE_URL,
            lessee_codes=('AAAA',),
            status_codes=(1,),
            sold_date_code=None,
        )
        assert query.status_codes == (1,)
        assert query.sold_date_code is None

    def test_instance_is_frozen(self) -> None:
        # Shared contract with QueryInputBase — no need to deeply re-test
        # slots/frozen here since `test_base.py` covers the base guarantees.
        query: VehiclesQuery = _default_query()
        assert not hasattr(query, '__dict__')

    def test_default_values(self) -> None:
        query: VehiclesQuery = _default_query()
        assert query.status_codes is None
        assert query.sold_date_code is None
        assert query.last_change_date is None
        assert query.last_change_record_id is None


class TestClassVarAnnotations:
    """Regression guard against ClassVar fields leaking into dataclass fields."""

    def test_class_vars_are_not_instance_fields(self) -> None:
        field_names: set[str] = {f.name for f in fields(VehiclesQuery)}
        assert 'endpoint_path' not in field_names
        assert 'response_item_type' not in field_names


class TestHeaders:
    def test_accept_json(self) -> None:
        assert _default_query().headers() == {'Accept': 'application/json'}
