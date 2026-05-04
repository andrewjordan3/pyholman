# tests/_storage/test_watermark.py
"""Tests for ``compute_most_recent_record_utc``."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from pyholman._storage import compute_most_recent_record_utc

__all__: list[str] = []


def _datetime_frame(values: list[datetime]) -> pd.DataFrame:
    """Build a one-column DataFrame with a UTC datetime[us] column."""
    return pd.DataFrame(
        {
            'last_change_date': pd.to_datetime(values, utc=True).astype(
                'datetime64[us, UTC]'
            )
        }
    )


class TestSnapshotOnly:
    def test_none_watermark_returns_none(self) -> None:
        # Snapshot-only endpoints declare ``watermark_column=None``.
        # The helper returns ``None`` regardless of the dataframe shape.
        frame: pd.DataFrame = pd.DataFrame({'id': [1, 2]})
        assert compute_most_recent_record_utc(frame, watermark_column=None) is None

    def test_none_watermark_with_empty_frame_returns_none(self) -> None:
        # The empty-frame check only fires when a watermark column is
        # named; snapshot endpoints bypass it entirely.
        frame: pd.DataFrame = pd.DataFrame({'id': []})
        assert compute_most_recent_record_utc(frame, watermark_column=None) is None


class TestColumnMax:
    def test_returns_max_as_python_datetime(self) -> None:
        oldest: datetime = datetime(2026, 1, 1, tzinfo=UTC)
        latest: datetime = datetime(2026, 4, 21, 12, 30, tzinfo=UTC)
        middle: datetime = datetime(2026, 3, 1, tzinfo=UTC)
        frame: pd.DataFrame = _datetime_frame([oldest, latest, middle])

        result = compute_most_recent_record_utc(
            frame, watermark_column='last_change_date'
        )

        assert isinstance(result, datetime)
        assert result == latest

    def test_single_row_returns_that_row_value(self) -> None:
        only: datetime = datetime(2026, 1, 1, tzinfo=UTC)
        frame: pd.DataFrame = _datetime_frame([only])

        assert (
            compute_most_recent_record_utc(frame, watermark_column='last_change_date')
            == only
        )


class TestEmptyFrame:
    def test_empty_frame_with_named_watermark_raises(self) -> None:
        # Even though the column exists in the frame schema, having
        # zero rows makes ``Series.max()`` return ``NaT`` —
        # silently corrupt metadata. The helper raises instead.
        frame: pd.DataFrame = pd.DataFrame(
            {'last_change_date': pd.Series([], dtype='datetime64[us, UTC]')}
        )

        with pytest.raises(ValueError, match='empty'):
            compute_most_recent_record_utc(frame, watermark_column='last_change_date')


class TestMissingColumn:
    def test_missing_column_raises_key_error(self) -> None:
        frame: pd.DataFrame = pd.DataFrame({'something_else': [1, 2]})

        with pytest.raises(KeyError, match='last_change_date'):
            compute_most_recent_record_utc(frame, watermark_column='last_change_date')
