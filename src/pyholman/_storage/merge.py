# src/pyholman/_storage/merge.py
"""
Replace-window merge for incremental updates.

``replace_window`` combines a freshly fetched DataFrame with a previously
persisted one under a single rule: any row in ``existing`` whose watermark
falls inside the refresh window is dropped and replaced by whatever Holman
returned for that window. Rows older than the window survive unchanged.

This strategy exists because incremental pulls must catch upstream
corrections and deletions, not just additions. If Holman fixes a typo on
an old record or removes a stale one, the next incremental pull is what
carries that change; a last-write-wins-by-primary-key merge would either
re-introduce the deleted row or keep the stale correction around. Treating
the window as authoritative — the latest pull *is* the truth for that
window — sidesteps those failure modes without needing primary-key
knowledge.

The function is pure: no I/O. Callers load ``existing`` from disk and
persist the result separately.
"""

import logging
from datetime import UTC, datetime

import pandas as pd

__all__: list[str] = ['replace_window']

logger: logging.Logger = logging.getLogger(__name__)


def replace_window(
    existing: pd.DataFrame,
    new: pd.DataFrame,
    watermark_column: str,
    window_start: datetime,
) -> pd.DataFrame:
    """
    Replace the refresh-window portion of ``existing`` with ``new``.

    Rows in ``existing`` whose ``watermark_column`` value is greater than
    or equal to ``window_start`` are dropped; the survivors are then
    concatenated with every row from ``new``. The result is sorted
    ascending by ``watermark_column``.

    NULL/NaT-watermark rows in ``existing`` are treated as outside the
    window and survive unchanged. This matches the watermark-based
    incremental-copy doctrine (Microsoft Fabric Copy Job's documented
    behavior is the canonical reference): NULL-watermark rows captured
    by an initial full refresh are not refreshed by subsequent
    incremental runs — a watermark-filtered API call cannot return
    them, so there is nothing fresh to merge — but they must not be
    deleted from on-disk state either. No de-duplication is needed
    because the source API cannot return NULL-watermark rows in an
    incremental pull, so ``new`` and the surviving NULL rows in
    ``outside_window`` are guaranteed disjoint.

    ``new`` is treated as the schema source of truth: ``outside_window``
    is cast to ``new.dtypes`` before concat. This is a no-op on
    Parquet (which preserves dtypes through the round-trip) and
    corrects the dtype drift that CSV introduces (``pd.read_csv``
    defaults all-NA columns to ``float64`` and infers others under
    rules that can disagree with the response model). Aligning dtypes
    pre-concat also avoids pandas' ``FutureWarning`` about result-dtype
    inference for frames containing all-NA entries.

    Args:
        existing: The currently persisted DataFrame. May be empty.
        new: Freshly fetched rows covering ``[window_start, now]``. May
            be empty; an empty ``new`` still drops existing rows inside
            the window (the Holman-returned-nothing-for-that-window case
            legitimately represents "all such rows were deleted").
        watermark_column: Name of a comparable column (typically a
            last-modified timestamp) used both to decide which existing
            rows fall inside the window and to sort the result.
        window_start: Inclusive lower bound of the refresh window.
            Must be timezone-aware and in UTC.

    Returns:
        A DataFrame with all surviving rows, sorted ascending by
        ``watermark_column`` and indexed with a fresh ``RangeIndex``
        starting at 0. NULL-watermark rows from ``existing`` are
        preserved and sort to the end (pandas sorts NaT last under
        ascending order). When both inputs are empty, the result is an
        empty DataFrame with the shared schema.

    Raises:
        KeyError: If ``watermark_column`` is absent from either
            ``existing`` or ``new``. The message names the column and
            the frame it is missing from.
        ValueError: If ``existing`` and ``new`` have different column
            sets (after the watermark-column check). The message lists
            the symmetric difference. Also raised if ``window_start``
            is naive (no tzinfo) or not in UTC.
    """
    _validate_watermark_column(
        dataframe=existing,
        watermark_column=watermark_column,
        frame_label='existing',
    )
    _validate_watermark_column(
        dataframe=new,
        watermark_column=watermark_column,
        frame_label='new',
    )
    _validate_schema_match(existing=existing, new=new)
    _validate_window_start_utc(window_start=window_start)

    logger.debug(
        'Replacing window: existing_rows=%d new_rows=%d watermark=%s window_start=%s',
        len(existing),
        len(new),
        watermark_column,
        window_start.isoformat(),
    )

    if existing.empty and new.empty:
        return new.iloc[0:0].copy().reset_index(drop=True)

    if existing.empty:
        return new.sort_values(by=watermark_column, kind='stable').reset_index(
            drop=True
        )

    # NULL/NaT watermarks are treated as outside the window: a
    # watermark-filtered API call cannot return them, so ``new`` will
    # not carry a refresh for them, and silently dropping them on
    # every incremental run would delete every NULL-watermark row that
    # the initial full refresh captured. ``NaT < window_start`` is
    # ``False``, so a plain ``<`` comparison would exclude them from
    # ``outside_window`` and lose them.
    existing_watermark: pd.Series = existing[watermark_column]
    outside_window: pd.DataFrame = existing.loc[
        existing_watermark.isna() | (existing_watermark < window_start)
    ]

    # ``new`` came from the Pydantic response model and is the schema
    # source of truth. Casting ``outside_window`` to ``new.dtypes`` is
    # a no-op on Parquet (which preserves dtypes) and corrects
    # CSV-roundtrip drift (``pd.read_csv`` defaults all-NA columns to
    # ``float64`` regardless of the column's declared type, and reads
    # every other column under inference rules that can disagree with
    # the response model). Doing the cast before concat also avoids
    # pandas' ``FutureWarning`` about how it will infer result dtypes
    # from frames containing all-NA entries — matching dtypes makes
    # the inference question moot.
    if not outside_window.empty:
        outside_window = outside_window.astype(new.dtypes.to_dict())

    # Filter empty frames before concat: a zero-row frame still trips
    # pandas' all-empty FutureWarning even when its dtypes match.
    frames_to_concat: list[pd.DataFrame] = [
        frame for frame in (outside_window, new) if not frame.empty
    ]
    if not frames_to_concat:
        combined: pd.DataFrame = outside_window.iloc[0:0].copy()
    elif len(frames_to_concat) == 1:
        combined = frames_to_concat[0].copy()
    else:
        combined = pd.concat(frames_to_concat, ignore_index=True)

    result: pd.DataFrame = combined.sort_values(
        by=watermark_column,
        kind='stable',
    ).reset_index(drop=True)

    logger.info(
        'Replaced window: existing_rows=%d new_rows=%d result_rows=%d',
        len(existing),
        len(new),
        len(result),
    )

    return result


def _validate_watermark_column(
    dataframe: pd.DataFrame,
    watermark_column: str,
    frame_label: str,
) -> None:
    """Raise ``KeyError`` if ``watermark_column`` is missing from ``dataframe``."""
    if watermark_column not in dataframe.columns:
        raise KeyError(
            f'Watermark column {watermark_column!r} is missing from the '
            f'{frame_label!r} DataFrame.'
        )


def _validate_schema_match(existing: pd.DataFrame, new: pd.DataFrame) -> None:
    """Raise ``ValueError`` if the two frames have different column sets."""
    existing_columns: set[str] = set(existing.columns)
    new_columns: set[str] = set(new.columns)
    if existing_columns == new_columns:
        return

    symmetric_difference: list[str] = sorted(
        existing_columns.symmetric_difference(new_columns)
    )
    raise ValueError(
        f'Schema mismatch between existing and new DataFrames. '
        f'Columns in only one frame: {symmetric_difference}'
    )


def _validate_window_start_utc(window_start: datetime) -> None:
    """Raise ``ValueError`` if ``window_start`` is naive or not UTC."""
    if window_start.tzinfo is None:
        raise ValueError(
            f'window_start must be timezone-aware UTC; got naive datetime '
            f'{window_start.isoformat()}.'
        )
    if window_start.utcoffset() != UTC.utcoffset(window_start):
        raise ValueError(
            f'window_start must be in UTC; got offset '
            f'{window_start.utcoffset()} ({window_start.isoformat()}).'
        )
