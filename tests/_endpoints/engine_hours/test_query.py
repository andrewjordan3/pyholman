# tests/_endpoints/engine_hours/test_query.py
"""Tests for the EngineHoursQuery dataclass."""

from dataclasses import fields
from urllib.parse import parse_qs, urlsplit

from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.engine_hours import EngineHours, EngineHoursQuery

__all__: list[str] = []


_DEFAULT_BASE_URL: str = 'https://api.holman.solutions'
_DEFAULT_PAGE_NUMBER: int = 1
_DEFAULT_PAGE_SIZE: int = 200


def _default_query(**overrides: object) -> EngineHoursQuery:
    construction_kwargs: dict[str, object] = {
        'base_url': _DEFAULT_BASE_URL,
        'lessee_codes': ('YYYY',),
    }
    construction_kwargs.update(overrides)
    return EngineHoursQuery(**construction_kwargs)  # type: ignore[arg-type]


class TestClassVarContract:
    def test_endpoint_path_points_to_basic_query(self) -> None:
        assert EngineHoursQuery.endpoint_path == (
            '/CustomerDataAPI/engine-hours/basic-query'
        )

    def test_response_item_type_is_engine_hours(self) -> None:
        assert EngineHoursQuery.response_item_type is EngineHours

    def test_is_query_input_base_subclass(self) -> None:
        assert issubclass(EngineHoursQuery, QueryInputBase)

    def test_response_item_type_is_response_model(self) -> None:
        assert issubclass(EngineHoursQuery.response_item_type, ResponseModel)


class TestUrl:
    def test_minimum_query_emits_only_required_params(self) -> None:
        full_url: str = _default_query().url(
            page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE
        )
        parsed = urlsplit(full_url)
        assert parsed.path == '/CustomerDataAPI/engine-hours/basic-query'

        parsed_query: dict[str, list[str]] = parse_qs(parsed.query)
        assert set(parsed_query) == {'lesseeCodes', 'pageNumber', 'pageSize'}
        assert parsed_query['lesseeCodes'] == ['YYYY']
        assert parsed_query['pageNumber'] == [str(_DEFAULT_PAGE_NUMBER)]
        assert parsed_query['pageSize'] == [str(_DEFAULT_PAGE_SIZE)]

    def test_lessee_codes_comma_join(self) -> None:
        params: dict[str, str] = _default_query(
            lessee_codes=('YYYY', 'XXXX')
        ).query_params(page_number=_DEFAULT_PAGE_NUMBER, page_size=_DEFAULT_PAGE_SIZE)
        assert params['lesseeCodes'] == 'YYYY,XXXX'


class TestDataclassShape:
    def test_no_endpoint_specific_fields(self) -> None:
        base_field_names: set[str] = {f.name for f in fields(QueryInputBase)}
        subclass_field_names: set[str] = {f.name for f in fields(EngineHoursQuery)}
        assert subclass_field_names == base_field_names

    def test_class_vars_are_not_instance_fields(self) -> None:
        field_names: set[str] = {f.name for f in fields(EngineHoursQuery)}
        assert 'endpoint_path' not in field_names
        assert 'response_item_type' not in field_names

    def test_instance_is_slotted(self) -> None:
        assert not hasattr(_default_query(), '__dict__')


class TestHeaders:
    def test_accept_json(self) -> None:
        assert _default_query().headers() == {'Accept': 'application/json'}
