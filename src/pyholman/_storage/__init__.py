# src/pyholman/_storage/__init__.py
"""Storage primitives for pyholman: parquet/CSV handlers, merge, metadata, watermark."""

from pyholman._storage.csv_handler import CsvHandler
from pyholman._storage.handler import StorageHandler, get_storage_handler
from pyholman._storage.merge import replace_window
from pyholman._storage.metadata import (
    StorageMetadata,
    StorageRunMode,
    get_pyholman_version,
)
from pyholman._storage.parquet_handler import ParquetHandler
from pyholman._storage.watermark import compute_most_recent_record_utc

__all__: list[str] = [
    'CsvHandler',
    'ParquetHandler',
    'StorageHandler',
    'StorageMetadata',
    'StorageRunMode',
    'compute_most_recent_record_utc',
    'get_pyholman_version',
    'get_storage_handler',
    'replace_window',
]
