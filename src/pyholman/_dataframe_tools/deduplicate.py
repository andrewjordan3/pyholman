# src/pyholman/_dataframe_tools/deduplicate.py
"""Drop byte-identical duplicate rows from a DataFrame."""

import pandas as pd

__all__: list[str] = ['deduplicate_dataframe']


def deduplicate_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of ``dataframe`` with byte-identical duplicate rows dropped.

    Uses every column to decide equality — two rows are considered
    duplicates only if every column's value matches. This is a safety
    net against Holman's habit of returning repeated records on some
    endpoints (observed heavily on contacts); genuine distinct records
    with a single column difference survive unchanged.

    Args:
        dataframe: Any pandas DataFrame.

    Returns:
        A new DataFrame with the same columns in the same order, rows
        in original order minus duplicates, and a fresh
        ``RangeIndex`` starting at 0.
    """
    return dataframe.drop_duplicates(ignore_index=True)
