# src/pyholman/_storage/handler.py
"""
Storage-handler Protocol and the concrete-class factory.

The :class:`StorageHandler` Protocol is the single read/write surface
that downstream pipeline code depends on. Concrete implementations
(:class:`~pyholman._storage.parquet_handler.ParquetHandler` and
:class:`~pyholman._storage.csv_handler.CsvHandler`) satisfy it
structurally — no inheritance from the Protocol is required.

:func:`get_storage_handler` is the only call site that needs to know
which concrete class to instantiate for a given output format. Adding a
new :class:`OutputFormat` member without extending the dispatch here
must produce a type-checker error; that is enforced via an exhaustive
``match`` whose arms cover every enum member.
"""

from pathlib import Path
from typing import Protocol

import pandas as pd

from pyholman._config import OutputConfig, OutputFormat
from pyholman._storage.csv_handler import CsvHandler
from pyholman._storage.metadata import StorageMetadata
from pyholman._storage.parquet_handler import ParquetHandler

__all__: list[str] = ['StorageHandler', 'get_storage_handler']


class StorageHandler(Protocol):
    """
    Single read/write surface for one resource's persisted data.

    A handler instance owns the paths for one resource and the policy
    (format, compression) for serializing it. Consumers depend on this
    Protocol; the concrete class is selected once at the edge by
    :func:`get_storage_handler` and threaded through the pipeline.

    Read-only attributes:
        data_path: Full path to the resource's data file, including
            extension. Pure path construction; access has no side
            effects on disk.
        metadata_path: Full path to the resource's per-format metadata
            sidecar (``metadata.<format>.json``). Pure path
            construction; access has no side effects on disk.
    """

    @property
    def data_path(self) -> Path: ...

    @property
    def metadata_path(self) -> Path: ...

    def to_dataframe(self) -> pd.DataFrame:
        """
        Read the data file from disk into a DataFrame.

        Returns:
            The DataFrame as serialized to disk. Concrete
            implementations preserve dtype and timezone information to
            the extent the underlying format allows.

        Raises:
            FileNotFoundError: If the data file does not exist.
        """
        ...

    def from_dataframe(self, dataframe: pd.DataFrame) -> None:
        """
        Write a DataFrame to the data file atomically.

        Side Effects:
            Creates the resource directory if it does not exist; writes
            atomically so a crash mid-write leaves any prior file
            intact.

        Args:
            dataframe: The DataFrame to persist. Must be non-empty.

        Raises:
            ValueError: If ``dataframe`` is empty.
        """
        ...

    def read_metadata(self) -> StorageMetadata | None:
        """
        Return the cached metadata sidecar, reading from disk on first call.

        Subsequent calls on the same instance return the cached value
        without touching disk. A missing sidecar caches as ``None``.

        Returns:
            The :class:`StorageMetadata` instance from disk, or ``None``
            if the sidecar does not exist.
        """
        ...

    def write_metadata(self, metadata: StorageMetadata) -> None:
        """
        Write the metadata sidecar atomically and update the in-memory cache.

        Side Effects:
            Creates the resource directory if it does not exist, then
            atomically writes the sidecar. Subsequent
            :meth:`read_metadata` calls return ``metadata`` without
            touching disk.

        Args:
            metadata: The :class:`StorageMetadata` instance to persist.
        """
        ...


def get_storage_handler(
    output_config: OutputConfig,
    working_directory: Path,
    resource_name: str,
) -> StorageHandler:
    """
    Construct the concrete :class:`StorageHandler` for the configured format.

    The dispatch is an exhaustive ``match`` over :class:`OutputFormat`;
    adding a new member without extending the match raises a static
    type-checker error (the function would fall off the end and return
    ``None`` against its declared return type).

    Args:
        output_config: The user's serialization configuration. The
            handler reads ``format`` to pick the concrete class and,
            for Parquet, threads ``compression`` into the constructor.
            The ``OutputConfig`` validators already reject the
            CSV-with-non-null-compression combination, so the factory
            does not re-check it.
        working_directory: Root directory under which the per-resource
            subdirectory lives. Not validated or created here; the
            handler creates the resource directory on first write.
        resource_name: Registered resource name; names the subdirectory
            and the data file.

    Returns:
        A concrete handler that satisfies :class:`StorageHandler`.
    """
    match output_config.format:
        case OutputFormat.PARQUET:
            return ParquetHandler(
                working_directory=working_directory,
                resource_name=resource_name,
                compression=output_config.compression,
            )
        case OutputFormat.CSV:
            return CsvHandler(
                working_directory=working_directory,
                resource_name=resource_name,
            )
