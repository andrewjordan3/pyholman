# src/pyholman/_core/filters.py
"""Base class for filter models supporting incremental window overrides."""

import logging
from datetime import datetime, timedelta
from typing import Any, ClassVar, Self

from pydantic import field_validator

from pyholman._core.frozen import FrozenModel

__all__: list[str] = ['IncrementalFilters']

logger: logging.Logger = logging.getLogger(__name__)


class IncrementalFilters(FrozenModel):
    """
    Base for per-endpoint filter models that support incremental refresh.

    Provides the universal watermark field used by every Holman delta-
    capable endpoint: ``last_change_date``, a tz-aware UTC cursor that
    the orchestrator stamps onto the filter before issuing a query.
    The :class:`ClassVar` ``WATERMARK_FIELD_NAME`` defaults to
    ``'last_change_date'``; subclasses can override it if a future
    endpoint uses a different watermark name (no current endpoint does).

    The :meth:`with_window_start` method takes a UTC datetime and
    returns a new validated instance with ``WATERMARK_FIELD_NAME``
    set to that value. :meth:`ResourcePreparer.build_query` uses this
    method to apply the resolved incremental window to the user-configured
    filters before building the query.

    Attributes:
        WATERMARK_FIELD_NAME: ClassVar naming the watermark filter
            field. Defaults to ``'last_change_date'``.
        last_change_date: Optional UTC cursor for delta queries. Must
            be timezone-aware and have a zero UTC offset. Naive or
            non-UTC values are rejected with error text that mirrors
            :func:`pyholman._core.query.base._serialize_query_value`.
    """

    WATERMARK_FIELD_NAME: ClassVar[str] = 'last_change_date'

    last_change_date: datetime | None = None

    @field_validator('last_change_date')
    @classmethod
    def _validate_last_change_date(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                f'last_change_date must be timezone-aware UTC; '
                f'got naive {value.isoformat()}'
            )
        if value.utcoffset() != timedelta(0):
            raise ValueError(
                f'last_change_date must be in UTC; got offset '
                f'{value.utcoffset()} ({value.isoformat()})'
            )
        return value

    def with_window_start(self, window_start: datetime) -> Self:
        """
        Return a new validated instance with the watermark field updated.

        Round-trips through ``model_validate`` so any field validators
        on the watermark field (tz-aware enforcement, etc.) run on the
        override value, not just on user-supplied input.

        Args:
            window_start: Inclusive lower bound to set on the watermark
                filter field. Must be tz-aware UTC; the underlying
                field validator on each filter model enforces this.

        Returns:
            A new instance of the same concrete class with
            ``WATERMARK_FIELD_NAME`` set to ``window_start`` and all
            other fields preserved.
        """
        # Exclude computed fields from the dump: ``model_dump`` includes
        # them by default in Pydantic v2, but ``model_validate`` rejects
        # them under ``extra='forbid'`` because they are not input
        # fields. Driving the round-trip off ``model_fields`` keeps the
        # set of keys to exactly the input surface of the concrete
        # subclass, regardless of whether it declares any
        # ``@computed_field`` attributes.
        computed_field_names: set[str] = set(type(self).model_computed_fields)
        updated_fields: dict[str, Any] = self.model_dump(
            exclude=computed_field_names,
        ) | {self.WATERMARK_FIELD_NAME: window_start}
        return type(self).model_validate(updated_fields)
