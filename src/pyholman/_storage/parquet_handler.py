# src/pyholman/_storage/parquet_handler.py
"""
Atomic, dtype-preserving Parquet I/O for pyholman.

Writes go through :func:`atomicwrites.atomic_write` so a crash mid-write
either leaves the prior file intact or leaves the target path missing —
never a partially written file. Timestamps are coerced to microsecond
precision without truncation (real nanoseconds raise), matching
BigQuery / Spark / DuckDB interoperability needs.

This module does not enforce a dtype scheme on input DataFrames; it
round-trips whatever pandas hands it, as long as the precision rules
above are satisfied. Callers are responsible for constructing DataFrames
with the intended dtypes.
"""

import logging
from pathlib import Path
from typing import ClassVar, Final, Literal

import pandas as pd
from atomicwrites import atomic_write

from pyholman._config import ParquetCompression
from pyholman._storage.handler_base import StorageHandlerBase

__all__: list[str] = [
    'ParquetHandler',
]

logger: logging.Logger = logging.getLogger(__name__)

# The data-file extension is a property of the format, not the resource;
# kept as a module constant so a name change lands in one place.
_PARQUET_EXTENSION: Final[str] = '.parquet'


def _write_parquet_file(
    dataframe: pd.DataFrame,
    file_path: Path,
    compression: ParquetCompression | None,
) -> None:
    """
    Write a DataFrame to ``file_path`` as a Parquet file, atomically.

    The write uses :func:`atomicwrites.atomic_write` with
    ``overwrite=True`` so an existing file at ``file_path`` is replaced
    only after the new content is fully written. A crash mid-write leaves
    the prior file (if any) in place.

    Timestamps are coerced to microsecond precision
    (``coerce_timestamps='us'``) and truncation is disallowed
    (``allow_truncated_timestamps=False``). Nanosecond-precision inputs
    whose sub-microsecond component is zero coerce cleanly; any real
    nanoseconds raise a ``ValueError`` from pyarrow.

    Args:
        dataframe: The DataFrame to write. Must have at least one row;
            empty DataFrames are rejected because an empty write almost
            always signals a missing upstream guard.
        file_path: Target path. Parent directory must already exist.
        compression: Compression codec, or ``None`` for uncompressed
            output. Passes through verbatim to
            :meth:`pandas.DataFrame.to_parquet`.

    Returns:
        None.

    Raises:
        ValueError: If ``dataframe`` is empty, or (from pyarrow) if any
            datetime column has a real nanosecond component.
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
        'Writing Parquet: path=%s rows=%d compression=%s',
        file_path,
        len(dataframe),
        compression.value if compression is not None else 'none',
    )

    # ``ParquetCompression`` is a StrEnum whose members are exactly the
    # string literals pandas' ``to_parquet`` accepts.
    compression_value: Literal['snappy', 'gzip', 'brotli', 'lz4', 'zstd'] | None = (
        compression.value if compression is not None else None
    )

    with atomic_write(str(file_path), mode='wb', overwrite=True) as binary_handle:
        dataframe.to_parquet(
            binary_handle,
            compression=compression_value,
            index=False,
            coerce_timestamps='us',
            allow_truncated_timestamps=False,
        )

    logger.info(
        'Wrote Parquet: path=%s rows=%d',
        file_path,
        len(dataframe),
    )


def _read_parquet_file(file_path: Path) -> pd.DataFrame:
    """
    Read a Parquet file from disk into a DataFrame with dtype preservation.

    Args:
        file_path: Path to the Parquet file.

    Returns:
        A DataFrame whose columns retain the dtypes stored in the file.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        pyarrow.lib.ArrowInvalid: If the file is not valid Parquet.
    """
    logger.debug('Reading Parquet: %s', file_path)
    dataframe: pd.DataFrame = pd.read_parquet(file_path)
    logger.debug(
        'Read Parquet: path=%s rows=%d',
        file_path,
        len(dataframe),
    )
    return dataframe


class ParquetHandler(StorageHandlerBase):
    """
    Parquet-backed :class:`~pyholman._storage.handler.StorageHandler`.

    Owns the data-file path
    (``<working_directory>/<resource_name>/<resource_name>.parquet``)
    and the metadata sidecar path inherited from the base. The actual
    serialization delegates to :func:`_write_parquet_file` and
    :func:`_read_parquet_file` so dtype-preservation, microsecond-coercion,
    and atomic-write semantics match the function-style helpers exactly.

    Args:
        working_directory: Root directory under which per-resource
            subdirectories live. Not created at construction.
        resource_name: Registered resource name; names the subdirectory
            and the data file.
        compression: Parquet compression codec, or ``None`` for
            uncompressed output. Defaults to
            :attr:`ParquetCompression.SNAPPY` to match the project's
            default Parquet output policy.
    """

    _format_label: ClassVar[str] = 'parquet'

    def __init__(
        self,
        working_directory: Path,
        resource_name: str,
        compression: ParquetCompression | None = ParquetCompression.SNAPPY,
    ) -> None:
        super().__init__(
            working_directory=working_directory,
            resource_name=resource_name,
        )
        self._compression: ParquetCompression | None = compression

    @property
    def data_path(self) -> Path:
        """
        Path to this resource's Parquet data file; pure path construction.
        """
        return self._resource_directory / f'{self._resource_name}{_PARQUET_EXTENSION}'

    def to_dataframe(self) -> pd.DataFrame:
        """
        Read the Parquet data file from disk into a DataFrame.

        Returns:
            The DataFrame as serialized to disk, with dtypes and
            timezone information preserved by Parquet.

        Raises:
            FileNotFoundError: If :attr:`data_path` does not exist.
        """
        return _read_parquet_file(self.data_path)

    def from_dataframe(self, dataframe: pd.DataFrame) -> None:
        """
        Write a DataFrame to the Parquet data file atomically.

        Side Effects:
            Creates the resource directory if it does not exist, then
            atomically writes the data file via
            :func:`_write_parquet_file`.

        Args:
            dataframe: The DataFrame to persist. Must be non-empty.

        Raises:
            ValueError: If ``dataframe`` is empty (raised by
                :func:`_write_parquet_file`).
        """
        self._ensure_resource_directory()
        _write_parquet_file(
            dataframe=dataframe,
            file_path=self.data_path,
            compression=self._compression,
        )
