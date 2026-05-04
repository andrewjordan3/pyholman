# src/pyholman/_core/response/base.py
"""Tolerant Pydantic base class for parsing Holman API responses."""

from typing import Any, ClassVar, Self

import pandas as pd
from pydantic import ConfigDict, model_validator

from pyholman._core.base import BaseHolmanModel
from pyholman._core.response.dataframe import build_dataframe_from_records

__all__: list[str] = ['ResponseModel']


class ResponseModel(BaseHolmanModel):
    """
    Base class for Pydantic models that parse Holman API responses.

    ResponseModel is the tolerant counterpart to FrozenModel. It is used for
    any model whose schema is controlled by Holman rather than by pyholman —
    primarily the per-endpoint response models (Vehicle, Contact, Maintenance
    record, Odometer reading) and their paginated wrappers.

    Guarantees:
        - **Immutable.** Same as FrozenModel (``frozen=True``). Response
          objects should not be mutated by caller code.
        - **Tolerant.** Unknown fields in the input JSON are silently dropped
          (``extra='ignore'``). This is the critical difference from
          FrozenModel: when Holman adds a field to their response schema,
          pyholman keeps working until we explicitly model the new field.
        - **Defaults validated.** Same as FrozenModel.

    Design note — why ``extra='ignore'`` and not ``extra='allow'``:
        ``extra='allow'`` would expose unknown fields as attributes, which
        sounds useful but creates a hazard: caller code can come to depend on
        undocumented fields that Holman may rename or remove without notice.
        ``extra='ignore'`` forces all supported fields to be declared
        explicitly on the model, keeping the pyholman-Holman contract visible
        in the source. If you need to discover what is being dropped during
        development, enable DEBUG logging in pyholman — the library logs
        unrecognized response keys at that level.

    When NOT to use this class:
        For models that pyholman itself controls (configs, query inputs,
        internal domain objects), use ``FrozenModel``. The strict validation
        there is valuable feedback that tolerance here would obscure.

    Example:
        Minimal vehicle response model::

            class VehicleResponse(ResponseModel):
                holman_vehicle_number: str = Field(alias='holmanVehicleNumber')
                vin: str
                lessee_code: str = Field(alias='lesseeCode')
                status_code: int = Field(alias='statusCode')
                model_year: str | None = Field(alias='modelYear', default=None)
                # ... other fields omitted for brevity.
                # Any Holman field not listed here is silently dropped.
    """

    model_config = ConfigDict(
        extra='ignore',
        frozen=True,
        validate_default=True,
        # populate_by_name allows constructing instances from either the
        # Python attribute name (holman_vehicle_number) or the JSON alias
        # (holmanVehicleNumber). This is convenient for tests that construct
        # responses programmatically using Python-native field names.
        populate_by_name=True,
    )

    # Python attribute name of the column the incremental orchestrator
    # uses as the high-water mark for ``replace_window`` merges. Subclasses
    # that support incremental pulls override this with the name of their
    # ``last_change_date``-equivalent field; subclasses that only support
    # full-refresh leave the default ``None``. The value intentionally
    # carries the snake_case Python name, not the camelCase Holman alias:
    # ``replace_window`` operates on DataFrames built from attribute names.
    watermark_column: ClassVar[str | None] = None

    @model_validator(mode='before')
    @classmethod
    def _strip_string_values(cls, data: Any) -> Any:
        # ``Any``: ``mode='before'`` validators receive the raw input
        # before Pydantic narrows it. For JSON-loaded responses that is
        # a dict; for direct model construction it may be a model
        # instance, a tuple of fields, etc. The ``isinstance`` guard
        # below restricts the strip to the dict case.
        """
        Strip leading and trailing whitespace from every string-valued input.

        Holman is inconsistent about whitespace on the wire: identifier
        fields ship as ``"            60250"``, code fields as
        ``"120 "``, free-text as ``"Unknown - "``. Stripping at the base
        class normalizes every endpoint's response uniformly without
        per-field validators.

        Only top-level string values are touched. Non-string values pass
        through unchanged; nested mappings are not recursed into
        (Pydantic recurses into nested-model fields by re-running their
        own validators). All-whitespace strings collapse to ``""``; the
        empty-string-to-``None`` decision belongs to per-field
        validators that have the field's domain knowledge, not to this
        wire-format normalization.
        """
        if not isinstance(data, dict):
            return data
        return {
            key: value.strip() if isinstance(value, str) else value
            for key, value in data.items()
        }

    @classmethod
    def records_to_dataframe(cls, records: list[Self]) -> pd.DataFrame:
        """
        Build a typed pandas DataFrame from a list of response-model records.

        Thin wrapper around
        :func:`pyholman._core.response.dataframe.build_dataframe_from_records`.
        See that function's docstring for the full dtype mapping and the
        list of annotations that raise.

        Args:
            records: List of records to materialize. An empty list is
                allowed and yields a DataFrame with the expected columns
                and dtypes and zero rows.

        Returns:
            A DataFrame whose columns match the model's field names in
            declaration order, each with the pandas nullable dtype chosen
            by the helper.

        Raises:
            TypeError: If any field annotation cannot be mapped to a
                supported scalar dtype.
        """
        return build_dataframe_from_records(model_class=cls, records=records)
