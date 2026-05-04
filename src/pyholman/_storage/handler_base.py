# src/pyholman/_storage/handler_base.py
"""
Shared base for the storage-handler concrete classes.

Holds the shared metadata-sidecar caching and resource-directory plumbing
so :class:`~pyholman._storage.parquet_handler.ParquetHandler` and
:class:`~pyholman._storage.csv_handler.CsvHandler` do not duplicate the
same logic. Consumers depend on the
:class:`~pyholman._storage.handler.StorageHandler` Protocol; this base
class is the implementation detail both concrete handlers inherit from.
Lives in its own module so the Protocol/factory module (``handler.py``)
can import the concrete handlers without an import cycle (concrete
handlers import this base; the factory imports the concrete handlers).
"""

import logging
from pathlib import Path
from typing import ClassVar

from pyholman._storage.metadata import StorageMetadata

__all__: list[str] = ['StorageHandlerBase']

logger: logging.Logger = logging.getLogger(__name__)


class StorageHandlerBase:
    """
    Shared base providing cached metadata I/O and resource-dir handling.

    Class state:
        ``_format_label`` — short identifier for the serialization
        format (e.g., ``'csv'`` or ``'parquet'``). Concrete subclasses
        must set this; it drives the metadata sidecar filename so two
        formats can coexist in the same per-resource directory without
        one clobbering the other.

    Instance state:
        ``_working_directory`` — root directory under which the
        per-resource subdirectory lives.
        ``_resource_name`` — registered resource name; the subdirectory
        beneath ``_working_directory`` is named after it.
        ``_cached_metadata`` — the most recently read or written
        :class:`StorageMetadata`, or ``None`` if either the disk read
        returned no sidecar or the cache is still cold.
        ``_metadata_was_read`` — True after the first ``read_metadata``
        call or any ``write_metadata`` call. The flag (rather than a
        sentinel value) keeps ``_cached_metadata`` strictly typed as
        ``StorageMetadata | None`` while still distinguishing
        "definitively absent on disk" from "have not looked yet".

    Args:
        working_directory: Root directory under which per-resource
            subdirectories live. Not validated and not created at
            construction; ``from_dataframe`` and ``write_metadata``
            create the resource subdirectory on demand.
        resource_name: Registered resource name (e.g., ``'vehicles'``).
            Stored verbatim and used to name both the subdirectory and
            (in concrete subclasses) the data file.
    """

    _format_label: ClassVar[str]

    def __init__(self, working_directory: Path, resource_name: str) -> None:
        self._working_directory: Path = working_directory
        self._resource_name: str = resource_name
        self._cached_metadata: StorageMetadata | None = None
        self._metadata_was_read: bool = False

    @property
    def _resource_directory(self) -> Path:
        """The per-resource subdirectory; pure path construction."""
        return self._working_directory / self._resource_name

    @property
    def metadata_path(self) -> Path:
        """
        Path to this resource's metadata sidecar (``metadata.<format>.json``).

        The sidecar filename is per-format (e.g., ``metadata.csv.json``,
        ``metadata.parquet.json``) so two formats can coexist in the
        same per-resource directory without one clobbering the other.

        Pure path construction; accessing this attribute neither reads
        from disk nor creates any directory.
        """
        return self._resource_directory / f'metadata.{self._format_label}.json'

    def read_metadata(self) -> StorageMetadata | None:
        """
        Return the cached metadata sidecar, reading from disk on first call.

        On the first call against a fresh handler instance, the sidecar
        at :attr:`metadata_path` is loaded via
        :meth:`StorageMetadata.from_json`. A missing sidecar is
        translated to ``None`` and that ``None`` is itself cached so a
        second call does not retry the disk read. Any other exception
        (validation failure, permission error) propagates unchanged.

        Subsequent calls on the same instance — including calls made
        after :meth:`write_metadata` — return the cached value without
        touching disk.

        Returns:
            The deserialized :class:`StorageMetadata`, or ``None`` if
            the sidecar does not exist on disk.

        Raises:
            pydantic.ValidationError: If the sidecar exists but its
                content does not satisfy :class:`StorageMetadata`.
        """
        if self._metadata_was_read:
            return self._cached_metadata

        try:
            self._cached_metadata = StorageMetadata.from_json(self.metadata_path)
        except FileNotFoundError:
            self._cached_metadata = None
        self._metadata_was_read = True
        return self._cached_metadata

    def write_metadata(self, metadata: StorageMetadata) -> None:
        """
        Write the metadata sidecar atomically and update the cache.

        Side Effects:
            Creates the resource directory if it does not exist, then
            atomically writes the sidecar via
            :meth:`StorageMetadata.to_json`. Updates the in-memory cache
            so the next :meth:`read_metadata` returns ``metadata``
            without touching disk.

        Args:
            metadata: The :class:`StorageMetadata` instance to persist.
        """
        self._ensure_resource_directory()
        metadata.to_json(self.metadata_path)
        self._cached_metadata = metadata
        self._metadata_was_read = True

    def _ensure_resource_directory(self) -> None:
        """
        Create the resource directory if it does not exist.

        Idempotent: ``parents=True`` allows missing intermediate
        directories, ``exist_ok=True`` allows a pre-existing directory.
        """
        self._resource_directory.mkdir(parents=True, exist_ok=True)
