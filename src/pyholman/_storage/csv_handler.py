# src/pyholman/_storage/csv_handler.py
"""
Atomic CSV I/O for pyholman.

CSV is a lossy format: pandas dtype information is not preserved across a
write/read round-trip, and timezone-aware datetimes are serialized as
strings that lose their tz attachment unless the reader is told what to
look for. Callers that need round-trip dtype fidelity should use the
Parquet handler (:mod:`pyholman._storage.parquet_handler`). This module
exists for portability — handoff to spreadsheets and tools that do not
read Parquet.

Writes go through :func:`atomicwrites.atomic_write` so a crash mid-write
either leaves the prior file intact or leaves the target path missing —
never a partially written file.
"""

import logging
from pathlib import Path
from typing import ClassVar, Final

import pandas as pd
from atomicwrites import atomic_write

from pyholman._storage.handler_base import StorageHandlerBase

__all__: list[str] = [
    'CsvHandler',
]

logger: logging.Logger = logging.getLogger(__name__)

# The data-file extension is a property of the format, not the resource;
# kept as a module constant so a name change lands in one place.
_CSV_EXTENSION: Final[str] = '.csv'


def _write_csv_file(dataframe: pd.DataFrame, file_path: Path) -> None:
    """
    Write a DataFrame to ``file_path`` as a UTF-8 CSV file, atomically.

    The write uses :func:`atomicwrites.atomic_write` with
    ``overwrite=True`` so an existing file at ``file_path`` is replaced
    only after the new content is fully written. A crash mid-write leaves
    the prior file (if any) in place.

    The index is not written. CSV is lossy for dtypes and for
    timezone-aware datetimes; see module docstring.

    Args:
        dataframe: The DataFrame to write. Must have at least one row;
            empty DataFrames are rejected because an empty write almost
            always signals a missing upstream guard.
        file_path: Target path. Parent directory must already exist.

    Returns:
        None.

    Raises:
        ValueError: If ``dataframe`` is empty.
        OSError: If the target directory is missing or not writable.

    Side Effects:
        Creates or atomically replaces ``file_path`` on disk.
    """
    if dataframe.empty:
        raise ValueError(
            f'Cannot write empty DataFrame to {file_path}. '
            f'Empty writes indicate a missing upstream guard.'
        )

    logger.debug(
        'Writing CSV: path=%s rows=%d',
        file_path,
        len(dataframe),
    )

    # ``newline=''`` disables Python's text-mode newline translation.
    # Without it, a Windows-mode ``'w'`` open turns every ``\n`` written
    # by pandas into ``\r\n``; pandas' ``to_csv`` already emits
    # ``os.linesep`` (``\r\n`` on Windows) per row, so the file lands as
    # ``\r\r\n``-separated. ``pandas.read_csv`` tolerates this; Excel
    # and Power BI treat each ``\r`` as a record terminator and parse a
    # blank row between every real row. ``atomic_write`` forwards
    # unknown kwargs to ``io.open`` via ``**open_kwargs``.
    with atomic_write(
        str(file_path),
        mode='w',
        encoding='utf-8',
        newline='',
        overwrite=True,
    ) as text_handle:
        dataframe.to_csv(text_handle, index=False)

    logger.info('Wrote CSV: path=%s rows=%d', file_path, len(dataframe))


def _read_csv_file(file_path: Path) -> pd.DataFrame:
    """
    Read a CSV file from disk into a DataFrame, with no dtype hints.

    CSV loses dtype information; guessing which columns should be dates
    or nullable integers belongs to the caller, not this layer.

    ``low_memory=False`` forces a single inference pass over the whole
    file rather than pandas' default chunk-by-chunk inference. Without
    it, a column whose value-shape varies across chunk boundaries
    (numeric in some rows, string in others — common for the
    client-defined ``aux_data_*`` / ``client_data_*`` fields) cannot be
    given a single dtype globally, and pandas falls back to ``object``
    while emitting a ``DtypeWarning``. Single-pass inference suppresses
    the warning and the per-chunk wasted work; the transient memory
    cost is trivial at pyholman's scale.

    Args:
        file_path: Path to the CSV file.

    Returns:
        A DataFrame with whatever dtypes :func:`pandas.read_csv` infers
        in a single pass.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
    """
    logger.debug('Reading CSV: %s', file_path)
    dataframe: pd.DataFrame = pd.read_csv(file_path, low_memory=False)
    logger.debug('Read CSV: path=%s rows=%d', file_path, len(dataframe))
    return dataframe


class CsvHandler(StorageHandlerBase):
    """
    CSV-backed :class:`~pyholman._storage.handler.StorageHandler`.

    Owns the data-file path
    (``<working_directory>/<resource_name>/<resource_name>.csv``) and
    the metadata sidecar path inherited from the base. The actual
    serialization delegates to :func:`_write_csv_file` and
    :func:`_read_csv_file`, so the dtype-loss and atomic-write semantics
    match the function-style helpers exactly.

    No ``compression`` knob: CSV with a non-null compression codec is
    rejected at :class:`~pyholman._config.OutputConfig` validation time
    (see ``_reject_compression_with_csv``), so the handler does not
    need to take or thread a compression value through.

    Args:
        working_directory: Root directory under which per-resource
            subdirectories live. Not created at construction.
        resource_name: Registered resource name; names the
            subdirectory and the data file.
    """

    _format_label: ClassVar[str] = 'csv'

    @property
    def data_path(self) -> Path:
        """Path to this resource's CSV data file; pure path construction."""
        return self._resource_directory / f'{self._resource_name}{_CSV_EXTENSION}'

    def to_dataframe(self) -> pd.DataFrame:
        """
        Read the CSV data file from disk into a DataFrame.

        CSV is lossy for dtypes; the returned frame has whatever dtypes
        :func:`pandas.read_csv` infers. Callers needing dtype fidelity
        should use the Parquet handler instead.

        Returns:
            The DataFrame as inferred from the CSV file.

        Raises:
            FileNotFoundError: If :attr:`data_path` does not exist.
        """
        return _read_csv_file(self.data_path)

    def from_dataframe(self, dataframe: pd.DataFrame) -> None:
        """
        Write a DataFrame to the CSV data file atomically.

        Side Effects:
            Creates the resource directory if it does not exist, then
            atomically writes the data file via :func:`_write_csv_file`.

        Args:
            dataframe: The DataFrame to persist. Must be non-empty.

        Raises:
            ValueError: If ``dataframe`` is empty (raised by
                :func:`_write_csv_file`).
        """
        self._ensure_resource_directory()
        _write_csv_file(dataframe=dataframe, file_path=self.data_path)
