# src/pyholman/_core/response/dataframe.py
"""
Typed-DataFrame construction for pyholman response models.

The single public entry point is :func:`build_dataframe_from_records`,
which a ``ResponseModel`` subclass calls through its
``records_to_dataframe`` classmethod. The helper is parameterized on a
``pydantic.BaseModel`` subclass so it does not have to import
``ResponseModel`` — avoiding a circular import with
``models/response/base.py`` — while still benefiting from the Pydantic
public interface (``model_fields``, ``model_dump``).
"""

import types
from datetime import datetime
from typing import Any, Union, cast, get_args, get_origin

import pandas as pd
from pandas.api.extensions import ExtensionDtype
from pydantic import BaseModel
from pydantic.fields import FieldInfo

__all__: list[str] = ['build_dataframe_from_records']


# =============================================================================
# Scalar-type → pandas dtype map
# =============================================================================
# Response models round-trip through a DataFrame using nullable pandas
# dtypes; every row in ``_SCALAR_TYPE_TO_PANDAS_DTYPE`` corresponds to
# one supported field annotation. A type not in this map raises
# ``TypeError`` from ``build_dataframe_from_records`` — intentionally, so
# a nested model or container-typed field fails loudly rather than
# collapsing to ``object`` dtype.
# =============================================================================
_SCALAR_TYPE_TO_PANDAS_DTYPE: dict[type, ExtensionDtype] = {
    int: pd.Int64Dtype(),
    float: pd.Float64Dtype(),
    str: pd.StringDtype(),
    bool: pd.BooleanDtype(),
    datetime: pd.DatetimeTZDtype(unit='us', tz='UTC'),
}

_PANDAS_DATETIME_DTYPE: pd.DatetimeTZDtype = pd.DatetimeTZDtype(unit='us', tz='UTC')


def build_dataframe_from_records[TModel: BaseModel](
    model_class: type[TModel],
    records: list[TModel],
) -> pd.DataFrame:
    """
    Build a typed pandas DataFrame from a list of Pydantic-model records.

    Column names are the Python attribute names (snake_case), not the
    Pydantic aliases. Dtypes come from each field's type annotation:

        int | None         → Int64
        float | None       → Float64
        str | None         → string
        bool | None        → boolean
        datetime | None    → datetime64[us, UTC]

    Plain (non-optional) versions of the same scalars map identically.
    Optional wrappers are unwrapped via ``typing.get_origin`` /
    ``typing.get_args``; any annotation that does not resolve to one of
    the supported scalars — nested models, ``list[T]``, ``dict[K, V]``,
    unions with multiple non-None arms, ``Literal``, and so on — is
    rejected with ``TypeError`` naming both the field and its annotation.

    Args:
        model_class: The Pydantic model class whose fields define the
            DataFrame schema.
        records: List of records to materialize. An empty list is
            allowed and yields a DataFrame with the expected columns and
            dtypes and zero rows.

    Returns:
        A DataFrame whose columns match the model's field names in
        declaration order, each with the pandas nullable dtype chosen
        above. Datetime columns are tz-aware UTC at microsecond
        precision. Empty strings in string columns are normalized to
        ``pd.NA`` — at the wire-format layer the Pydantic models
        faithfully preserve ``""`` as Holman sent it, but at the
        DataFrame boundary missing-value semantics are uniform.

    Raises:
        TypeError: If any field annotation cannot be mapped to a
            supported scalar dtype.
    """
    dtype_map: dict[str, ExtensionDtype] = _build_dtype_map(model_class=model_class)

    if not records:
        return pd.DataFrame(
            {
                column_name: pd.Series(dtype=column_dtype)
                for column_name, column_dtype in dtype_map.items()
            }
        )

    record_rows: list[dict[str, Any]] = [record.model_dump() for record in records]
    # ``dict[str, Any]``: Pydantic's ``model_dump`` returns a mapping with
    # heterogeneous scalar / container values; the subsequent dtype cast
    # narrows per column.
    dataframe: pd.DataFrame = pd.DataFrame(record_rows)
    # Enforce column order to match the model's field declaration
    # order, not whatever order the dict-keys happened to arrive in.
    dataframe = dataframe[list(dtype_map.keys())]

    for column_name, column_dtype in dtype_map.items():
        if column_dtype == _PANDAS_DATETIME_DTYPE:
            dataframe[column_name] = pd.to_datetime(
                dataframe[column_name],
                utc=True,
            ).astype(_PANDAS_DATETIME_DTYPE)
        else:
            dataframe[column_name] = dataframe[column_name].astype(column_dtype)

    _replace_empty_strings_with_na(dataframe=dataframe, dtype_map=dtype_map)

    return dataframe


def _replace_empty_strings_with_na(
    dataframe: pd.DataFrame,
    dtype_map: dict[str, ExtensionDtype],
) -> None:
    """
    In-place replace ``""`` with ``pd.NA`` on every ``StringDtype`` column.

    The Pydantic layer mirrors Holman's wire format faithfully — a
    field that arrives as ``""`` stays ``""`` on the model. At the
    DataFrame boundary that distinction stops being useful: empty
    string and ``null`` are functionally equivalent for downstream
    analytics. Normalizing to ``pd.NA`` aligns string columns with
    every other dtype's missing-value handling.

    Targets ``StringDtype`` columns specifically; the other extension
    dtypes (Int64, Float64, BooleanDtype, DatetimeTZDtype) cannot
    carry an empty-string value.
    """
    string_dtype: pd.StringDtype = pd.StringDtype()
    for column_name, column_dtype in dtype_map.items():
        if column_dtype == string_dtype:
            dataframe[column_name] = dataframe[column_name].replace('', pd.NA)


def _build_dtype_map(model_class: type[BaseModel]) -> dict[str, ExtensionDtype]:
    """Return ``{field_name: pandas_dtype}`` for every declared field."""
    dtype_map: dict[str, ExtensionDtype] = {}
    for field_name, field_info in model_class.model_fields.items():
        scalar_type: type = _resolve_scalar_field_type(
            field_name=field_name,
            field_info=field_info,
            owning_model_name=model_class.__name__,
        )
        dtype_map[field_name] = _SCALAR_TYPE_TO_PANDAS_DTYPE[scalar_type]
    return dtype_map


def _resolve_scalar_field_type(
    field_name: str,
    field_info: FieldInfo,
    owning_model_name: str,
) -> type:
    """
    Reduce a field's annotation to a single supported scalar type.

    Handles plain scalars, ``Optional[T]`` / ``T | None`` wrappers, and
    unions whose only non-None arm is a supported scalar. Anything
    richer — nested models, containers, ``Literal``, multi-arm unions —
    raises ``TypeError`` with a message naming the field and its
    annotation, so the caller learns both where the schema is
    incompatible and what annotation it encountered.
    """
    raw_annotation: Any = field_info.annotation
    # ``Any``: ``FieldInfo.annotation`` is declared ``Any`` by Pydantic —
    # it may be a plain ``type``, a ``types.UnionType``, a
    # ``typing.Union``, a generic alias, a ``Literal``, etc. The helpers
    # below narrow it.
    non_none_types: list[Any] = _strip_none_from_union(raw_annotation)
    # ``list[Any]``: each element mirrors ``raw_annotation`` — one of the
    # annotation shapes listed above — and is validated below.

    if len(non_none_types) != 1:
        raise TypeError(
            f'{owning_model_name}.{field_name} has unsupported annotation '
            f'{raw_annotation!r}: build_dataframe_from_records requires a '
            f'single non-None scalar type, found {len(non_none_types)}.'
        )

    candidate_type: Any = non_none_types[0]
    # ``Any``: same rationale — may be any annotation shape until the
    # membership check below narrows it to a supported scalar ``type``.
    if candidate_type not in _SCALAR_TYPE_TO_PANDAS_DTYPE:
        raise TypeError(
            f'{owning_model_name}.{field_name} has unsupported annotation '
            f'{raw_annotation!r}: build_dataframe_from_records supports '
            f'{sorted(t.__name__ for t in _SCALAR_TYPE_TO_PANDAS_DTYPE)} only.'
        )
    # The membership check above guarantees ``candidate_type`` is one of
    # the keys of ``_SCALAR_TYPE_TO_PANDAS_DTYPE``, all of which are
    # ``type`` objects; ``cast`` narrows for the static checker.
    return cast(type, candidate_type)


def _strip_none_from_union(annotation: Any) -> list[Any]:
    # ``Any`` on both sides: the input is a Pydantic field annotation
    # (see :func:`_resolve_scalar_field_type`); the output preserves
    # whatever annotation shapes the union carried.
    """
    Return the non-``NoneType`` arms of a union, or ``[annotation]`` as-is.

    ``Optional[T]`` and ``T | None`` both present as unions containing
    ``NoneType``; both yield ``[T]``. A bare non-union annotation yields
    a single-element list so the caller treats every case uniformly.
    """
    origin: Any = get_origin(annotation)
    # ``Any``: ``typing.get_origin`` returns ``Any`` in the stdlib stubs
    # — the origin may be ``Union``, ``types.UnionType``, a generic
    # alias, or ``None`` for a plain type.
    if origin is Union or origin is types.UnionType:
        return [
            argument for argument in get_args(annotation) if argument is not type(None)
        ]
    return [annotation]
