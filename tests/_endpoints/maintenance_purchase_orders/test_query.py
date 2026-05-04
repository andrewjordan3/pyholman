# tests/_endpoints/maintenance_purchase_orders/test_query.py
"""Tests for the MaintenancePurchaseOrderQuery dataclass."""

from dataclasses import fields
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrder,
    MaintenancePurchaseOrderQuery,
)

__all__: list[str] = []


_DEFAULT_BASE_URL: str = 'https://api.holman.solutions'
_DEFAULT_PAGE_NUMBER: int = 1
_DEFAULT_PAGE_SIZE: int = 200


def _default_query(**overrides: object) -> MaintenancePurchaseOrderQuery:
    construction_kwargs: dict[str, object] = {
        'base_url': _DEFAULT_BASE_URL,
        'lessee_codes': ('XXXX',),
    }
    construction_kwargs.update(overrides)
    return MaintenancePurchaseOrderQuery(**construction_kwargs)  # type: ignore[arg-type]


class TestClassVarContract:
    def test_endpoint_path_points_to_basic_query(self) -> None:
        assert MaintenancePurchaseOrderQuery.endpoint_path == (
            '/CustomerDataAPI/maintenance/purchase-orders/basic-query'
        )

    def test_response_item_type_is_maintenance_purchase_order(self) -> None:
        assert (
            MaintenancePurchaseOrderQuery.response_item_type is MaintenancePurchaseOrder
        )

    def test_is_query_input_base_subclass(self) -> None:
        assert issubclass(MaintenancePurchaseOrderQuery, QueryInputBase)

    def test_response_item_type_is_response_model(self) -> None:
        assert issubclass(
            MaintenancePurchaseOrderQuery.response_item_type, ResponseModel
        )


class TestUrl:
    def test_minimum_query_emits_only_required_params(self) -> None:
        full_url: str = _default_query().url(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        parsed = urlsplit(full_url)
        assert parsed.path == (
            '/CustomerDataAPI/maintenance/purchase-orders/basic-query'
        )

        parsed_query: dict[str, list[str]] = parse_qs(parsed.query)
        assert set(parsed_query) == {'lesseeCodes', 'pageNumber', 'pageSize'}
        assert parsed_query['lesseeCodes'] == ['XXXX']
        assert parsed_query['pageNumber'] == [str(_DEFAULT_PAGE_NUMBER)]
        assert parsed_query['pageSize'] == [str(_DEFAULT_PAGE_SIZE)]

    def test_lessee_codes_comma_join(self) -> None:
        query: MaintenancePurchaseOrderQuery = _default_query(
            lessee_codes=('AAAA', 'XXXX')
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['lesseeCodes'] == 'AAAA,XXXX'


class TestQueryParams:
    def test_last_change_date_serializes_in_millisecond_format(self) -> None:
        query: MaintenancePurchaseOrderQuery = _default_query(
            last_change_date=datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC),
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['lastChangeDate'] == '2026-04-20T14:30:45.000Z'

    def test_last_change_record_id_passes_through(self) -> None:
        query: MaintenancePurchaseOrderQuery = _default_query(
            last_change_record_id=100000004
        )
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert params['lastChangeRecordId'] == '100000004'

    def test_none_valued_optional_fields_are_absent(self) -> None:
        query: MaintenancePurchaseOrderQuery = _default_query()
        params: dict[str, str] = query.query_params(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        assert 'lastChangeDate' not in params
        assert 'lastChangeRecordId' not in params


class TestDataclassShape:
    def test_no_endpoint_specific_fields(self) -> None:
        # The maintenance POs endpoint accepts only the base-class fields.
        # Confirm the subclass adds zero of its own to keep that contract
        # explicit against accidental future drift.
        base_field_names: set[str] = {f.name for f in fields(QueryInputBase)}
        subclass_field_names: set[str] = {
            f.name for f in fields(MaintenancePurchaseOrderQuery)
        }
        assert subclass_field_names == base_field_names

    def test_class_vars_are_not_instance_fields(self) -> None:
        field_names: set[str] = {f.name for f in fields(MaintenancePurchaseOrderQuery)}
        assert 'endpoint_path' not in field_names
        assert 'response_item_type' not in field_names

    def test_instance_is_slotted(self) -> None:
        assert not hasattr(_default_query(), '__dict__')


class TestHeaders:
    def test_accept_json(self) -> None:
        assert _default_query().headers() == {'Accept': 'application/json'}
