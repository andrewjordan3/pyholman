# src/pyholman/_storage/watermark.py
"""
Watermark extraction for storage metadata.

Single helper, :func:`compute_most_recent_record_utc`, used by the
pipeline's ``persist`` step to derive the
:attr:`StorageMetadata.most_recent_record_utc` value from the dataframe
about to be written.

Format-agnostic, dataframe-shaped: the input is the in-memory dataframe
the storage handler is about to serialize, not the file on disk. This
matches the pipeline's data flow — ``persist`` already has the
dataframe in scope and would otherwise re-read what it just wrote.
"""

import logging
from datetime import datetime
from typing import Any

import pandas as pd

__all__: list[str] = ['compute_most_recent_record_utc']

logger: logging.Logger = logging.getLogger(__name__)


def compute_most_recent_record_utc(
    dataframe: pd.DataFrame,
    watermark_column: str | None,
) -> datetime | None:
    """
    Return the maximum value of the watermark column as a Python datetime.

    Args:
        dataframe: The dataframe being persisted. Must be non-empty
            when ``watermark_column`` is not ``None`` — the storage
            handler rejects empty writes upstream, so empty inputs
            here indicate a pipeline ordering bug.
        watermark_column: The watermark column name from the response
            model's ``watermark_column`` ClassVar, or ``None`` for
            snapshot-only endpoints.

    Returns:
        - ``None`` if ``watermark_column`` is ``None`` (snapshot-only
          endpoint that does not stamp a record anchor).
        - Otherwise, the maximum value in ``dataframe[watermark_column]``,
          coerced to a Python ``datetime`` via ``.to_pydatetime()``.

    Raises:
        ValueError: If ``watermark_column`` is given but ``dataframe``
            is empty. ``pd.Series.max()`` on an empty datetime Series
            returns ``NaT``, which would silently corrupt metadata; a
            loud failure beats a silent ``NaT`` round-trip.
        KeyError: If ``watermark_column`` is given but not in
            ``dataframe.columns``.
        AttributeError: If the column dtype is not datetime-like (which
            would indicate a pipeline bug — incremental resources have
            datetime watermark columns by construction).
    """
    if watermark_column is None:
        return None

    if dataframe.empty:
        raise ValueError(
            f'Cannot compute most_recent_record_utc on an empty DataFrame; '
            f'watermark_column={watermark_column!r}. The storage handler '
            f'rejects empty writes upstream, so this state indicates a '
            f'pipeline ordering bug.'
        )

    if watermark_column not in dataframe.columns:
        raise KeyError(
            f'watermark_column {watermark_column!r} is not present in the '
            f'DataFrame; columns are {list(dataframe.columns)!r}.'
        )

    # ``Any`` follows the column dtype: ``Series.max()`` returns the
    # column's native scalar type and pandas' static stubs do not narrow
    # it. The ``.to_pydatetime()`` call below requires a Timestamp; the
    # ``AttributeError`` raised on a non-Timestamp value is documented
    # in the function's contract.
    column_max: Any = dataframe[watermark_column].max()
    result: datetime = column_max.to_pydatetime()
    return result
