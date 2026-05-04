# tests/_core/response/test_dataframe.py
"""Tests for ``ResponseModel.records_to_dataframe`` / ``build_dataframe_from_records``."""

from datetime import UTC, datetime
from typing import Literal

import pandas as pd
import pytest
from pydantic import Field

from pyholman._core import ResponseModel

__all__: list[str] = []


class _AllDtypes(ResponseModel):
    int_value: int | None = Field(alias='intValue', default=None)
    float_value: float | None = Field(alias='floatValue', default=None)
    str_value: str | None = Field(alias='strValue', default=None)
    bool_value: bool | None = Field(alias='boolValue', default=None)
    datetime_value: datetime | None = Field(alias='datetimeValue', default=None)
    required_str: str = Field(alias='requiredStr')


_EXPECTED_COLUMN_ORDER: list[str] = [
    'int_value',
    'float_value',
    'str_value',
    'bool_value',
    'datetime_value',
    'required_str',
]

_EXPECTED_DTYPES: dict[str, str] = {
    'int_value': 'Int64',
    'float_value': 'Float64',
    'str_value': 'string',
    'bool_value': 'boolean',
    'datetime_value': 'datetime64[us, UTC]',
    'required_str': 'string',
}


class TestEmptyList:
    def test_empty_list_returns_zero_row_dataframe_with_typed_columns(
        self,
    ) -> None:
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([])

        assert len(dataframe) == 0
        assert list(dataframe.columns) == _EXPECTED_COLUMN_ORDER
        for column_name, expected_dtype in _EXPECTED_DTYPES.items():
            assert str(dataframe[column_name].dtype) == expected_dtype


class TestPopulatedRecords:
    def test_single_fully_populated_record(self) -> None:
        record: _AllDtypes = _AllDtypes(
            int_value=1,
            float_value=1.5,
            str_value='alpha',
            bool_value=True,
            datetime_value=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            required_str='req',
        )

        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert len(dataframe) == 1
        assert dataframe['int_value'].to_numpy().tolist() == [1]
        assert dataframe['float_value'].to_numpy().tolist() == [1.5]
        assert dataframe['str_value'].to_numpy().tolist() == ['alpha']
        assert dataframe['bool_value'].to_numpy().tolist() == [True]
        assert dataframe['required_str'].to_numpy().tolist() == ['req']
        for column_name, expected_dtype in _EXPECTED_DTYPES.items():
            assert str(dataframe[column_name].dtype) == expected_dtype

    def test_single_record_all_optionals_none_keeps_nullable_dtypes(
        self,
    ) -> None:
        record: _AllDtypes = _AllDtypes(required_str='req')
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert len(dataframe) == 1
        for column_name in ('int_value', 'float_value', 'str_value', 'bool_value'):
            assert pd.isna(dataframe[column_name].iloc[0])
            assert str(dataframe[column_name].dtype) == _EXPECTED_DTYPES[column_name]
        assert pd.isna(dataframe['datetime_value'].iloc[0])
        assert str(dataframe['datetime_value'].dtype) == 'datetime64[us, UTC]'

    def test_multiple_records_mixing_populated_and_none(self) -> None:
        populated_record: _AllDtypes = _AllDtypes(
            int_value=10,
            float_value=2.5,
            str_value='x',
            bool_value=False,
            datetime_value=datetime(2026, 1, 1, tzinfo=UTC),
            required_str='row-1',
        )
        sparse_record: _AllDtypes = _AllDtypes(required_str='row-2')

        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe(
            [populated_record, sparse_record]
        )

        assert len(dataframe) == 2
        for column_name, expected_dtype in _EXPECTED_DTYPES.items():
            assert str(dataframe[column_name].dtype) == expected_dtype
        # Spot-check that each column kept its value at row 0 and NA at row 1.
        assert dataframe['int_value'].iloc[0] == 10
        assert pd.isna(dataframe['int_value'].iloc[1])


class TestColumnNamesUseSnakeCase:
    def test_columns_are_python_names_not_aliases(self) -> None:
        record: _AllDtypes = _AllDtypes(required_str='req')
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert list(dataframe.columns) == _EXPECTED_COLUMN_ORDER
        for alias in ('intValue', 'floatValue', 'strValue', 'boolValue'):
            assert alias not in dataframe.columns


class TestDatetimeColumnTimezone:
    def test_datetime_column_has_utc_timezone(self) -> None:
        record: _AllDtypes = _AllDtypes(
            datetime_value=datetime(2026, 2, 8, tzinfo=UTC),
            required_str='req',
        )
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert dataframe['datetime_value'].dt.tz is not None
        assert str(dataframe['datetime_value'].dt.tz) == 'UTC'


class TestUnsupportedAnnotations:
    def test_list_field_rejected(self) -> None:
        class _ListField(ResponseModel):
            items: list[str]

        with pytest.raises(TypeError, match=r'_ListField\.items.*list\[str\]'):
            _ListField.records_to_dataframe([])

    def test_dict_field_rejected(self) -> None:
        class _DictField(ResponseModel):
            mapping: dict[str, int]

        with pytest.raises(TypeError, match=r'_DictField\.mapping'):
            _DictField.records_to_dataframe([])

    def test_nested_model_field_rejected(self) -> None:
        class _Inner(ResponseModel):
            value: int

        class _Outer(ResponseModel):
            inner: _Inner

        with pytest.raises(TypeError, match=r'_Outer\.inner'):
            _Outer.records_to_dataframe([])

    def test_two_non_none_arm_union_rejected(self) -> None:
        class _IntOrStr(ResponseModel):
            value: int | str

        with pytest.raises(TypeError, match=r'_IntOrStr\.value'):
            _IntOrStr.records_to_dataframe([])

    def test_literal_field_rejected(self) -> None:
        class _LiteralField(ResponseModel):
            mode: Literal['a', 'b']

        with pytest.raises(TypeError, match=r'_LiteralField\.mode'):
            _LiteralField.records_to_dataframe([])


class TestEmptyStringNormalization:
    """
    String columns return ``pd.NA`` instead of ``""`` for missing values.

    The Pydantic models faithfully mirror Holman's wire format (``""``
    is preserved on the model). The DataFrame layer normalizes so that
    every column type uses the same missing-value sentinel
    (``pd.NA``).
    """

    def test_empty_string_in_string_column_becomes_na(self) -> None:
        record: _AllDtypes = _AllDtypes(str_value='', required_str='')
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert pd.isna(dataframe['str_value'].iloc[0])
        assert pd.isna(dataframe['required_str'].iloc[0])

    def test_non_empty_strings_pass_through_unchanged(self) -> None:
        populated_record: _AllDtypes = _AllDtypes(
            str_value='alpha',
            required_str='req',
        )
        empty_record: _AllDtypes = _AllDtypes(str_value='', required_str='')

        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe(
            [populated_record, empty_record]
        )

        assert dataframe['str_value'].iloc[0] == 'alpha'
        assert dataframe['required_str'].iloc[0] == 'req'
        assert pd.isna(dataframe['str_value'].iloc[1])
        assert pd.isna(dataframe['required_str'].iloc[1])

    def test_other_dtype_columns_unaffected(self) -> None:
        # Int64, Float64, BooleanDtype, DatetimeTZDtype cannot carry an
        # empty-string value to begin with; the normalization is a
        # no-op on them. Verify their populated values survive.
        record: _AllDtypes = _AllDtypes(
            int_value=42,
            float_value=3.14,
            str_value='',
            bool_value=False,
            datetime_value=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
            required_str='req',
        )
        dataframe: pd.DataFrame = _AllDtypes.records_to_dataframe([record])

        assert dataframe['int_value'].iloc[0] == 42
        assert dataframe['float_value'].iloc[0] == 3.14
        assert bool(dataframe['bool_value'].iloc[0]) is False
        assert dataframe['datetime_value'].iloc[0] == datetime(
            2026, 4, 29, 12, 0, tzinfo=UTC
        )
        # The string column for the same record is now NA — the
        # other-types-unaffected guarantee is that everything else
        # survives the normalization pass.
        assert pd.isna(dataframe['str_value'].iloc[0])
