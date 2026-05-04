# tests/_storage/test_merge.py
"""Tests for ``replace_window``."""

import warnings
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from pyholman._storage import replace_window

__all__: list[str] = []


def _frame(
    ids: list[int],
    labels: list[str],
    watermarks: list[str | None],
) -> pd.DataFrame:
    """Build a small frame with the three columns the merge tests use.

    A ``None`` entry in ``watermarks`` becomes a ``NaT`` value, which is
    how the storage layer represents a NULL-watermark row on disk.
    """
    return pd.DataFrame(
        {
            'id': pd.array(ids, dtype='Int64'),
            'label': pd.array(labels, dtype='string'),
            'updated_at': pd.to_datetime(
                watermarks,
                utc=True,
                format='ISO8601',
            ).astype('datetime64[us, UTC]'),
        }
    )


def _empty_like(reference: pd.DataFrame) -> pd.DataFrame:
    """Empty frame with the same schema as ``reference``."""
    return reference.iloc[0:0].copy()


class TestWindowBehavior:
    def test_full_replace_when_window_starts_before_every_existing_row(
        self,
    ) -> None:
        # window_start is before the earliest existing watermark, so every
        # existing row is inside the window and gets replaced by ``new``.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['old-1', 'old-2'],
            watermarks=['2026-02-10', '2026-02-11'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[1, 2, 3],
            labels=['new-1', 'new-2', 'new-3'],
            watermarks=['2026-02-12', '2026-02-13', '2026-02-14'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1, 2, 3]
        assert merged_frame['label'].tolist() == ['new-1', 'new-2', 'new-3']

    def test_no_overlap_when_every_existing_row_predates_window(self) -> None:
        # Every existing watermark is strictly less than window_start, so
        # every existing row survives unchanged and the result is their
        # concatenation with ``new``, sorted.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['archived-1', 'archived-2'],
            watermarks=['2026-01-10', '2026-01-11'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[3, 4],
            labels=['fresh-3', 'fresh-4'],
            watermarks=['2026-02-10', '2026-02-11'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1, 2, 3, 4]
        assert merged_frame['label'].tolist() == [
            'archived-1',
            'archived-2',
            'fresh-3',
            'fresh-4',
        ]

    def test_partial_overlap_keeps_outside_and_replaces_inside(self) -> None:
        # One existing row (id=1) is outside the window, one (id=2) is
        # inside. The inside row is dropped; ``new`` supplies what should
        # live in the window.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['outside', 'inside-stale'],
            watermarks=['2026-01-01', '2026-02-05'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2, 3],
            labels=['inside-fresh', 'inside-new'],
            watermarks=['2026-02-10', '2026-02-11'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1, 2, 3]
        assert merged_frame['label'].tolist() == [
            'outside',
            'inside-fresh',
            'inside-new',
        ]

    def test_corrections_scenario_new_value_wins(self) -> None:
        # Motivating use case: Holman corrects an existing record. The
        # existing row and the new row share the same ``id`` but differ
        # in ``label``. The replace-window strategy guarantees the new
        # (corrected) value survives; a last-write-wins merge that
        # preferred older watermarks would silently keep the stale copy.
        existing_frame: pd.DataFrame = _frame(
            ids=[1],
            labels=['typo-stale'],
            watermarks=['2026-02-05'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[1],
            labels=['corrected'],
            watermarks=['2026-02-10'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1]
        assert merged_frame['label'].tolist() == ['corrected']

    def test_deletions_scenario_row_absent_from_new_is_dropped(self) -> None:
        # Motivating use case: Holman deletes a record upstream. The
        # existing frame has R1 and R2 inside the window; the new pull
        # returned only R1. R2 must not survive — the replace-window
        # strategy drops it because it was inside the window.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['keeper', 'deleted-upstream'],
            watermarks=['2026-02-05', '2026-02-06'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[1],
            labels=['keeper'],
            watermarks=['2026-02-10'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1]
        assert merged_frame['label'].tolist() == ['keeper']


class TestEmptyInputs:
    def test_existing_empty_returns_sorted_new(self) -> None:
        existing_frame: pd.DataFrame = _empty_like(_frame([], [], []))
        new_frame: pd.DataFrame = _frame(
            ids=[2, 1],
            labels=['two', 'one'],
            watermarks=['2026-02-11', '2026-02-10'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1, 2]

    def test_new_empty_with_no_existing_rows_in_window(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[2, 1],
            labels=['two', 'one'],
            watermarks=['2026-01-11', '2026-01-10'],
        )
        new_frame: pd.DataFrame = _empty_like(existing_frame)

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1, 2]

    def test_new_empty_with_some_existing_rows_in_window(self) -> None:
        # Empty ``new`` is a valid "everything in that window was deleted"
        # signal; existing rows inside the window must still be dropped.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['outside', 'inside'],
            watermarks=['2026-01-10', '2026-02-05'],
        )
        new_frame: pd.DataFrame = _empty_like(existing_frame)

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1]
        assert merged_frame['label'].tolist() == ['outside']

    def test_both_empty_returns_empty_with_shared_schema(self) -> None:
        existing_frame: pd.DataFrame = _empty_like(_frame([], [], []))
        new_frame: pd.DataFrame = _empty_like(_frame([], [], []))

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert len(merged_frame) == 0
        assert list(merged_frame.columns) == ['id', 'label', 'updated_at']


class TestValidationFailures:
    def test_missing_watermark_in_existing(self) -> None:
        existing_without_watermark: pd.DataFrame = pd.DataFrame(
            {'id': pd.array([1], dtype='Int64'), 'label': ['x']}
        )
        new_frame: pd.DataFrame = _frame(
            ids=[1], labels=['y'], watermarks=['2026-02-10']
        )

        with pytest.raises(KeyError, match=r"'updated_at'.*'existing'"):
            replace_window(
                existing=existing_without_watermark,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

    def test_missing_watermark_in_new(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[1], labels=['x'], watermarks=['2026-01-10']
        )
        new_without_watermark: pd.DataFrame = pd.DataFrame(
            {'id': pd.array([2], dtype='Int64'), 'label': ['y']}
        )

        with pytest.raises(KeyError, match=r"'updated_at'.*'new'"):
            replace_window(
                existing=existing_frame,
                new=new_without_watermark,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

    def test_schema_mismatch_raises_value_error_naming_diff(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[1], labels=['x'], watermarks=['2026-01-10']
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2], labels=['y'], watermarks=['2026-02-10']
        ).assign(extra_column=['surprise'])

        with pytest.raises(ValueError, match='extra_column'):
            replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

    def test_naive_window_start_rejected(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[1], labels=['x'], watermarks=['2026-01-10']
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2], labels=['y'], watermarks=['2026-02-10']
        )
        naive_window_start: datetime = datetime(2026, 2, 1)  # noqa: DTZ001 -- naive is the condition under test

        with pytest.raises(ValueError, match='timezone-aware'):
            replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=naive_window_start,
            )

    def test_non_utc_window_start_rejected(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[1], labels=['x'], watermarks=['2026-01-10']
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2], labels=['y'], watermarks=['2026-02-10']
        )
        eastern_offset: timezone = timezone(timedelta(hours=-5))
        non_utc_window_start: datetime = datetime(2026, 2, 1, tzinfo=eastern_offset)

        with pytest.raises(ValueError, match='UTC'):
            replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=non_utc_window_start,
            )


class TestNullWatermarkPreservation:
    """
    NULL-watermark rows in ``existing`` must survive an incremental
    merge unchanged. Holman's API cannot return them via a watermark
    filter — ``NULL > X`` is false for every X — so they never appear
    in ``new``, and a plain ``existing[wm] < window_start`` filter
    drops them because ``NaT < datetime`` is also false. The merge
    therefore has to short-circuit NaT to "outside the window."

    Real-world impact: vehicles with a NULL ``last_change_date`` (8%
    of one fleet's first pull) were silently deleted on every
    incremental run before this fix.
    """

    def test_null_watermark_row_survives_when_window_is_in_the_past(
        self,
    ) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['null-wm', 'old'],
            watermarks=[None, '2026-01-10'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[3],
            labels=['fresh'],
            watermarks=['2026-02-10'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        # Both NULL-watermark and old rows are outside the window and
        # survive; the new row joins them.
        assert sorted(merged_frame['id'].tolist()) == [1, 2, 3]
        assert set(merged_frame['label'].tolist()) == {'null-wm', 'old', 'fresh'}

    def test_null_watermark_row_survives_alongside_inside_window_replacement(
        self,
    ) -> None:
        # Mix: a NULL row, an outside-window row, and an inside-window
        # row. NULL and outside survive; inside is replaced by ``new``.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2, 3],
            labels=['null-wm', 'outside', 'inside-stale'],
            watermarks=[None, '2026-01-10', '2026-02-05'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[3, 4],
            labels=['inside-fresh', 'inside-new'],
            watermarks=['2026-02-10', '2026-02-11'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        result_pairs: set[tuple[int, str]] = set(
            zip(
                merged_frame['id'].tolist(),
                merged_frame['label'].tolist(),
                strict=True,
            )
        )
        assert result_pairs == {
            (1, 'null-wm'),
            (2, 'outside'),
            (3, 'inside-fresh'),
            (4, 'inside-new'),
        }

    def test_null_watermark_row_survives_when_new_is_empty(self) -> None:
        # The deletions-of-empty-window scenario must not accidentally
        # take NULL-watermark rows out with it.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['null-wm', 'inside'],
            watermarks=[None, '2026-02-05'],
        )
        new_frame: pd.DataFrame = _empty_like(existing_frame)

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert merged_frame['id'].tolist() == [1]
        assert merged_frame['label'].tolist() == ['null-wm']

    def test_null_watermark_row_survives_when_window_starts_before_history(
        self,
    ) -> None:
        # Even when ``window_start`` is before every non-null watermark
        # (so every non-null existing row is replaced), the NULL row
        # still must survive — it cannot have been refreshed by the
        # API call under any window choice.
        existing_frame: pd.DataFrame = _frame(
            ids=[1, 2],
            labels=['null-wm', 'will-be-replaced'],
            watermarks=[None, '2026-02-10'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2],
            labels=['replacement'],
            watermarks=['2026-02-11'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
        )

        result_pairs: set[tuple[int, str]] = set(
            zip(
                merged_frame['id'].tolist(),
                merged_frame['label'].tolist(),
                strict=True,
            )
        )
        assert result_pairs == {(1, 'null-wm'), (2, 'replacement')}


class TestSchemaAlignmentAndWarnings:
    """
    ``new`` came from the Pydantic response model and is the schema
    source of truth. ``replace_window`` casts ``outside_window`` to
    ``new.dtypes`` before concat. The cast is a no-op on Parquet
    (which preserves dtypes) and corrects the dtype drift CSV
    introduces (``pd.read_csv`` defaults all-NA columns to ``float64``
    and infers others under rules that can disagree with the response
    model). Aligning dtypes pre-concat also avoids pandas'
    ``FutureWarning`` about result-dtype inference for frames
    containing all-NA entries.
    """

    @staticmethod
    def _csv_drifted_existing(
        watermarks: list[str],
        labels_as_strings: list[str],
    ) -> pd.DataFrame:
        # Simulate the CSV-roundtrip frame: ``label`` came back as
        # plain ``object`` rather than the response model's ``string``
        # dtype.
        return pd.DataFrame(
            {
                'id': pd.array(list(range(1, len(watermarks) + 1)), dtype='Int64'),
                'label': pd.Series(labels_as_strings, dtype='object'),
                'updated_at': pd.to_datetime(
                    watermarks,
                    utc=True,
                    format='ISO8601',
                ).astype('datetime64[us, UTC]'),
            }
        )

    def test_outside_window_is_cast_to_new_dtypes(self) -> None:
        # Existing has ``label`` as object; new has it as the
        # response-model ``string`` dtype. The merged result must
        # carry the new-side dtype on every column.
        existing_frame: pd.DataFrame = self._csv_drifted_existing(
            watermarks=['2026-01-10'],
            labels_as_strings=['drifted'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2],
            labels=['fresh'],
            watermarks=['2026-02-10'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        # Every column matches new's dtype, not existing's drifted dtype.
        assert merged_frame.dtypes.to_dict() == new_frame.dtypes.to_dict()

    def test_concat_emits_no_future_warning_with_all_na_column(self) -> None:
        # Real-world reproducer: an all-NA column in ``existing``
        # (CSV-loaded ``float64`` because every value is missing)
        # against a typed string column in ``new`` previously tripped
        # ``FutureWarning: The behavior of DataFrame concatenation
        # with empty or all-NA entries is deprecated``.
        existing_frame: pd.DataFrame = pd.DataFrame(
            {
                'id': pd.array([1], dtype='Int64'),
                # All-NA column read back as float64 — mismatched with
                # ``new``'s typed-string column of the same name.
                'label': pd.Series([float('nan')], dtype='float64'),
                'updated_at': pd.to_datetime(
                    ['2026-01-10'],
                    utc=True,
                    format='ISO8601',
                ).astype('datetime64[us, UTC]'),
            }
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2],
            labels=['fresh'],
            watermarks=['2026-02-10'],
        )

        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter('always')
            replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

        future_warnings: list[warnings.WarningMessage] = [
            warning
            for warning in captured_warnings
            if issubclass(warning.category, FutureWarning)
        ]
        assert future_warnings == []

    def test_empty_outside_window_emits_no_warning(self) -> None:
        # Every existing row falls inside the window, so
        # ``outside_window`` is empty; the concat path must not warn.
        existing_frame: pd.DataFrame = _frame(
            ids=[1],
            labels=['inside'],
            watermarks=['2026-02-05'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2],
            labels=['fresh'],
            watermarks=['2026-02-10'],
        )

        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter('always')
            merged_frame: pd.DataFrame = replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

        assert merged_frame['id'].tolist() == [2]
        assert [
            warning
            for warning in captured_warnings
            if issubclass(warning.category, FutureWarning)
        ] == []

    def test_empty_new_with_outside_window_rows_emits_no_warning(self) -> None:
        # Holman returned nothing for the window; ``new`` is empty.
        # The single-non-empty-frame path must not warn either.
        existing_frame: pd.DataFrame = _frame(
            ids=[1],
            labels=['outside'],
            watermarks=['2026-01-10'],
        )
        new_frame: pd.DataFrame = _empty_like(existing_frame)

        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter('always')
            merged_frame: pd.DataFrame = replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )

        assert merged_frame['id'].tolist() == [1]
        assert [
            warning
            for warning in captured_warnings
            if issubclass(warning.category, FutureWarning)
        ] == []

    def test_uncastable_outside_window_value_propagates(self) -> None:
        # Genuine schema drift: ``existing`` has a string in a column
        # that ``new`` declares as ``Int64``. The cast must not be
        # silently rescued — the upstream response-model evolution is
        # the right fix, and pyholman's job is to flag the mismatch.
        existing_frame: pd.DataFrame = pd.DataFrame(
            {
                'id': pd.Series(['not-an-int'], dtype='string'),
                'label': pd.array(['outside'], dtype='string'),
                'updated_at': pd.to_datetime(
                    ['2026-01-10'],
                    utc=True,
                    format='ISO8601',
                ).astype('datetime64[us, UTC]'),
            }
        )
        new_frame: pd.DataFrame = _frame(
            ids=[2],
            labels=['fresh'],
            watermarks=['2026-02-10'],
        )

        with pytest.raises((ValueError, TypeError)):
            replace_window(
                existing=existing_frame,
                new=new_frame,
                watermark_column='updated_at',
                window_start=datetime(2026, 2, 1, tzinfo=UTC),
            )


class TestIndex:
    def test_result_has_fresh_rangeindex(self) -> None:
        existing_frame: pd.DataFrame = _frame(
            ids=[10, 20],
            labels=['x', 'y'],
            watermarks=['2026-01-10', '2026-01-11'],
        )
        new_frame: pd.DataFrame = _frame(
            ids=[30, 40],
            labels=['z', 'w'],
            watermarks=['2026-02-10', '2026-02-11'],
        )

        merged_frame: pd.DataFrame = replace_window(
            existing=existing_frame,
            new=new_frame,
            watermark_column='updated_at',
            window_start=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert isinstance(merged_frame.index, pd.RangeIndex)
        assert merged_frame.index.start == 0
        assert list(merged_frame.index) == [0, 1, 2, 3]
