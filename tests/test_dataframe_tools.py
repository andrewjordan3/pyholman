# tests/test_dataframe_tools.py
"""Tests for ``deduplicate_dataframe``."""

import pandas as pd

from pyholman._dataframe_tools import deduplicate_dataframe

__all__: list[str] = []


class TestIdenticalRows:
    def test_exact_duplicates_collapsed_to_one(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': [1, 1, 1],
                'b': ['x', 'x', 'x'],
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert len(result) == 1
        assert result.iloc[0].to_dict() == {'a': 1, 'b': 'x'}

    def test_original_order_preserved_across_surviving_rows(self) -> None:
        # Three distinct rows interleaved with duplicates; the helper
        # keeps the first occurrence of each, in original order.
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': [1, 2, 1, 3, 2, 1],
                'b': ['p', 'q', 'p', 'r', 'q', 'p'],
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert result['a'].tolist() == [1, 2, 3]
        assert result['b'].tolist() == ['p', 'q', 'r']


class TestDistinctRows:
    def test_rows_differing_in_one_column_survive(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': [1, 1, 1],
                'b': ['x', 'y', 'z'],
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert len(result) == 3
        assert result['b'].tolist() == ['x', 'y', 'z']

    def test_rows_differing_across_all_columns_survive(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': [1, 2, 3],
                'b': ['x', 'y', 'z'],
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert len(result) == 3


class TestEmptyFrame:
    def test_empty_frame_round_trips_with_columns_preserved(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': pd.Series([], dtype='int64'),
                'b': pd.Series([], dtype='object'),
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert len(result) == 0
        assert list(result.columns) == ['a', 'b']
        assert result['a'].dtype == 'int64'
        assert result['b'].dtype == 'object'


class TestColumnOrder:
    def test_column_order_preserved(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'zeta': [1, 1],
                'alpha': [2, 2],
                'mike': [3, 3],
            }
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert list(result.columns) == ['zeta', 'alpha', 'mike']


class TestIndex:
    def test_output_has_fresh_range_index_starting_at_zero(self) -> None:
        # Caller may pass in a DataFrame with a non-default index; the
        # helper normalizes to a RangeIndex so downstream writers see a
        # predictable shape.
        input_df: pd.DataFrame = pd.DataFrame(
            {'a': [1, 1, 2, 2, 3]},
            index=[100, 200, 300, 400, 500],
        )
        result: pd.DataFrame = deduplicate_dataframe(input_df)
        assert isinstance(result.index, pd.RangeIndex)
        assert list(result.index) == [0, 1, 2]


class TestPurity:
    def test_original_input_is_not_mutated(self) -> None:
        input_df: pd.DataFrame = pd.DataFrame(
            {
                'a': [1, 1, 2],
                'b': ['x', 'x', 'y'],
            }
        )
        snapshot_a: list[int] = input_df['a'].tolist()
        snapshot_b: list[str] = input_df['b'].tolist()
        snapshot_len: int = len(input_df)

        deduplicate_dataframe(input_df)

        assert input_df['a'].tolist() == snapshot_a
        assert input_df['b'].tolist() == snapshot_b
        assert len(input_df) == snapshot_len
