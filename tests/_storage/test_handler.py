# tests/_storage/test_handler.py
"""
Tests for the storage-handler Protocol, the concrete handlers, and the
factory. Behavior shared between handlers is parametrized; format-specific
behavior (Parquet dtype preservation, CSV inference) gets a dedicated
test.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
import pytest

from pyholman._config import (
    OutputConfig,
    OutputFormat,
    ParquetCompression,
)
from pyholman._storage import (
    CsvHandler,
    ParquetHandler,
    StorageHandler,
    StorageMetadata,
    StorageRunMode,
    get_storage_handler,
    metadata as metadata_module,
)

__all__: list[str] = []


# =============================================================================
# Shared helpers
# =============================================================================


_RESOURCE_NAME: Final[str] = 'things'
_PLACEHOLDER_FILTERS_HASH: Final[str] = '0' * 64


def _make_parquet_handler(
    working_directory: Path,
    *,
    compression: ParquetCompression | None = ParquetCompression.SNAPPY,
) -> ParquetHandler:
    return ParquetHandler(
        working_directory=working_directory,
        resource_name=_RESOURCE_NAME,
        compression=compression,
    )


def _make_csv_handler(working_directory: Path) -> CsvHandler:
    return CsvHandler(
        working_directory=working_directory,
        resource_name=_RESOURCE_NAME,
    )


HandlerFactory = Callable[[Path], StorageHandler]


def _parquet_factory(working_directory: Path) -> StorageHandler:
    return _make_parquet_handler(working_directory)


def _csv_factory(working_directory: Path) -> StorageHandler:
    return _make_csv_handler(working_directory)


_HANDLER_FACTORIES: list[tuple[str, HandlerFactory]] = [
    ('parquet', _parquet_factory),
    ('csv', _csv_factory),
]


def _all_dtypes_frame() -> pd.DataFrame:
    """Three-row frame exercising every project-supported nullable dtype."""
    return pd.DataFrame(
        {
            'int_col': pd.array([1, 2, 3], dtype='Int64'),
            'float_col': pd.array([1.5, 2.5, 3.5], dtype='Float64'),
            'string_col': pd.array(['alpha', 'beta', 'gamma'], dtype='string'),
            'bool_col': pd.array([True, False, True], dtype='boolean'),
            'datetime_col': pd.to_datetime(
                ['2024-01-01', '2024-01-02', '2024-01-03'],
                utc=True,
            ).astype('datetime64[us, UTC]'),
        }
    )


def _example_metadata() -> StorageMetadata:
    """Minimal valid :class:`StorageMetadata` for round-trip tests."""
    instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    return StorageMetadata(
        endpoint=_RESOURCE_NAME,
        pyholman_version='0.0.0-test',
        run_mode=StorageRunMode.FULL_REFRESH,
        run_started_utc=instant,
        run_completed_utc=instant,
        most_recent_record_utc=instant,
        record_count=3,
        output_format=OutputFormat.PARQUET,
        compression=ParquetCompression.SNAPPY,
        filters_hash=_PLACEHOLDER_FILTERS_HASH,
    )


# =============================================================================
# Path attributes
# =============================================================================


class TestPaths:
    def test_parquet_data_path_uses_parquet_extension(self, tmp_path: Path) -> None:
        handler: ParquetHandler = _make_parquet_handler(tmp_path)
        assert (
            handler.data_path == tmp_path / _RESOURCE_NAME / f'{_RESOURCE_NAME}.parquet'
        )

    def test_csv_data_path_uses_csv_extension(self, tmp_path: Path) -> None:
        handler: CsvHandler = _make_csv_handler(tmp_path)
        assert handler.data_path == tmp_path / _RESOURCE_NAME / f'{_RESOURCE_NAME}.csv'

    @pytest.mark.parametrize(
        ('label', 'factory', 'expected_sidecar_name'),
        [
            ('parquet', _parquet_factory, 'metadata.parquet.json'),
            ('csv', _csv_factory, 'metadata.csv.json'),
        ],
        ids=['parquet', 'csv'],
    )
    def test_metadata_path_is_per_format_sidecar_under_resource_dir(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
        expected_sidecar_name: str,
    ) -> None:
        # Each format owns its own metadata sidecar so two formats can
        # coexist in the same per-resource directory without one
        # clobbering the other on a re-run under a different format.
        del label
        handler: StorageHandler = factory(tmp_path)
        assert (
            handler.metadata_path
            == tmp_path / _RESOURCE_NAME / expected_sidecar_name
        )

    def test_two_formats_have_distinct_metadata_paths_in_same_directory(
        self,
        tmp_path: Path,
    ) -> None:
        # Real workflow: same resource written under both Parquet and
        # CSV (Parquet for downstream tooling, CSV for spreadsheet
        # handoff). Both sidecars must coexist beside both data files
        # without colliding.
        parquet_handler: StorageHandler = _parquet_factory(tmp_path)
        csv_handler: StorageHandler = _csv_factory(tmp_path)

        assert parquet_handler.metadata_path != csv_handler.metadata_path
        assert (
            parquet_handler.metadata_path.parent == csv_handler.metadata_path.parent
        )

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_construction_and_path_access_have_no_disk_side_effects(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        # Pre-condition: working dir exists, but resource subdir does not.
        assert tmp_path.exists()
        resource_directory: Path = tmp_path / _RESOURCE_NAME
        assert not resource_directory.exists()

        handler: StorageHandler = factory(tmp_path)
        # Touching every path attribute must not create any directory.
        _ = handler.data_path
        _ = handler.metadata_path

        assert not resource_directory.exists()


# =============================================================================
# Round-trip
# =============================================================================


class TestRoundTrip:
    def test_parquet_handler_preserves_full_nullable_dtype_set(
        self,
        tmp_path: Path,
    ) -> None:
        # Parquet round-trips dtype information; this is the format's
        # job and the reason :class:`ParquetHandler` is the default.
        source_frame: pd.DataFrame = _all_dtypes_frame()
        handler: ParquetHandler = _make_parquet_handler(tmp_path)

        handler.from_dataframe(source_frame)
        restored_frame: pd.DataFrame = handler.to_dataframe()

        pd.testing.assert_frame_equal(restored_frame, source_frame)

    def test_csv_handler_round_trips_values_via_string_inference(
        self,
        tmp_path: Path,
    ) -> None:
        # CSV is lossy for dtypes; the underlying ``_write_csv_file`` /
        # ``_read_csv_file`` have a dedicated test pinning the inferred
        # dtypes for a given fixture (``test_csv_handler.py``). At the
        # handler level we only assert value equality after a
        # string-cast — handler behavior must match the function-style
        # helpers' behavior, no more, no less.
        source_frame: pd.DataFrame = pd.DataFrame(
            {
                'id': [1, 2, 3],
                'name': ['alpha', 'beta', 'gamma'],
                'score': [1.5, 2.5, 3.5],
                'flag': [True, False, True],
            }
        )
        handler: CsvHandler = _make_csv_handler(tmp_path)

        handler.from_dataframe(source_frame)
        restored_frame: pd.DataFrame = handler.to_dataframe()

        assert list(restored_frame.columns) == list(source_frame.columns)
        assert len(restored_frame) == len(source_frame)
        for column_name in source_frame.columns:
            assert (
                restored_frame[column_name].astype(str).tolist()
                == source_frame[column_name].astype(str).tolist()
            )


# =============================================================================
# Empty DataFrame and missing file
# =============================================================================


class TestEmptyDataFrame:
    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_from_dataframe_with_empty_frame_raises(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)
        empty_frame: pd.DataFrame = pd.DataFrame({'col': pd.array([], dtype='Int64')})

        with pytest.raises(ValueError, match='empty'):
            handler.from_dataframe(empty_frame)

        # The data file must not have been created.
        assert not handler.data_path.exists()


class TestMissingDataFile:
    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_to_dataframe_with_missing_file_raises_file_not_found(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)

        with pytest.raises(FileNotFoundError):
            handler.to_dataframe()


# =============================================================================
# Resource-directory creation
# =============================================================================


class TestResourceDirectoryCreation:
    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_read_methods_do_not_create_resource_directory(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)
        resource_directory: Path = tmp_path / _RESOURCE_NAME
        assert not resource_directory.exists()

        # Both read paths exit without mutating the filesystem.
        assert handler.read_metadata() is None
        with pytest.raises(FileNotFoundError):
            handler.to_dataframe()

        assert not resource_directory.exists()

    def test_parquet_from_dataframe_creates_resource_directory(
        self,
        tmp_path: Path,
    ) -> None:
        handler: ParquetHandler = _make_parquet_handler(tmp_path)
        resource_directory: Path = tmp_path / _RESOURCE_NAME
        assert not resource_directory.exists()

        handler.from_dataframe(_all_dtypes_frame())

        assert resource_directory.is_dir()
        assert handler.data_path.exists()

    def test_csv_from_dataframe_creates_resource_directory(
        self,
        tmp_path: Path,
    ) -> None:
        handler: CsvHandler = _make_csv_handler(tmp_path)
        resource_directory: Path = tmp_path / _RESOURCE_NAME
        assert not resource_directory.exists()

        handler.from_dataframe(pd.DataFrame({'id': [1]}))

        assert resource_directory.is_dir()
        assert handler.data_path.exists()

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_write_metadata_creates_resource_directory(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)
        resource_directory: Path = tmp_path / _RESOURCE_NAME
        assert not resource_directory.exists()

        handler.write_metadata(_example_metadata())

        assert resource_directory.is_dir()
        assert handler.metadata_path.exists()


# =============================================================================
# Metadata read / write round-trip
# =============================================================================


class TestMetadataReadWrite:
    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_read_metadata_returns_none_when_sidecar_missing(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)
        assert handler.read_metadata() is None

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_write_then_read_returns_equal_metadata_via_fresh_instance(
        self,
        tmp_path: Path,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        original_handler: StorageHandler = factory(tmp_path)
        original_metadata: StorageMetadata = _example_metadata()

        original_handler.write_metadata(original_metadata)

        # A fresh instance must read the value back from disk
        # identically — bypasses the in-memory cache.
        replacement_handler: StorageHandler = factory(tmp_path)
        restored_metadata: StorageMetadata | None = replacement_handler.read_metadata()
        assert restored_metadata == original_metadata


# =============================================================================
# Metadata caching
# =============================================================================


class TestMetadataCaching:
    """
    Cache behavior is implementation-shared across the concrete handlers
    (it lives on the private base), so the tests parametrize over both
    classes to confirm the contract holds for each.
    """

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_two_read_calls_hit_disk_only_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)
        # Seed a real sidecar so ``from_json`` has something valid to
        # return on its (sole) disk read.
        handler.write_metadata(_example_metadata())

        # Reset cache state by constructing a fresh handler that points
        # at the same paths.
        replacement_handler: StorageHandler = factory(tmp_path)

        from_json_call_count: int = 0
        original_from_json = StorageMetadata.from_json

        def _counting_from_json(file_path: Path) -> StorageMetadata:
            nonlocal from_json_call_count
            from_json_call_count += 1
            return original_from_json(file_path)

        monkeypatch.setattr(
            metadata_module.StorageMetadata,
            'from_json',
            classmethod(lambda _cls, file_path: _counting_from_json(file_path)),
        )

        first: StorageMetadata | None = replacement_handler.read_metadata()
        second: StorageMetadata | None = replacement_handler.read_metadata()

        assert first is not None
        assert first is second  # same object — second call returned the cache
        assert from_json_call_count == 1

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_write_metadata_seeds_cache_so_read_does_not_touch_disk(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)

        def _explode(_cls: type, file_path: Path) -> StorageMetadata:
            del file_path
            raise AssertionError(
                'from_json must not run after a write seeded the cache'
            )

        # Patch *after* construction but *before* the read so any disk
        # read fails the test.
        handler.write_metadata(_example_metadata())
        monkeypatch.setattr(
            metadata_module.StorageMetadata,
            'from_json',
            classmethod(_explode),
        )

        cached: StorageMetadata | None = handler.read_metadata()
        assert cached is not None
        assert cached == _example_metadata()

    @pytest.mark.parametrize(
        ('label', 'factory'),
        _HANDLER_FACTORIES,
        ids=[label for label, _ in _HANDLER_FACTORIES],
    )
    def test_missing_sidecar_caches_none_and_does_not_retry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        label: str,
        factory: HandlerFactory,
    ) -> None:
        del label
        handler: StorageHandler = factory(tmp_path)

        from_json_call_count: int = 0
        original_from_json = StorageMetadata.from_json

        def _counting_from_json(file_path: Path) -> StorageMetadata:
            nonlocal from_json_call_count
            from_json_call_count += 1
            return original_from_json(file_path)

        monkeypatch.setattr(
            metadata_module.StorageMetadata,
            'from_json',
            classmethod(lambda _cls, file_path: _counting_from_json(file_path)),
        )

        first: StorageMetadata | None = handler.read_metadata()
        second: StorageMetadata | None = handler.read_metadata()

        assert first is None
        assert second is None
        # Still exactly one disk read — the absence is itself cached.
        assert from_json_call_count == 1

    def test_two_separate_instances_maintain_independent_caches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first_handler: ParquetHandler = _make_parquet_handler(tmp_path)
        first_handler.write_metadata(_example_metadata())

        # Two fresh handlers pointing at the same paths.
        second_handler: ParquetHandler = _make_parquet_handler(tmp_path)
        third_handler: ParquetHandler = _make_parquet_handler(tmp_path)

        from_json_call_count: int = 0
        original_from_json = StorageMetadata.from_json

        def _counting_from_json(file_path: Path) -> StorageMetadata:
            nonlocal from_json_call_count
            from_json_call_count += 1
            return original_from_json(file_path)

        monkeypatch.setattr(
            metadata_module.StorageMetadata,
            'from_json',
            classmethod(lambda _cls, file_path: _counting_from_json(file_path)),
        )

        # Each fresh instance reads disk once; caches are not shared.
        second_handler.read_metadata()
        third_handler.read_metadata()
        assert from_json_call_count == 2


# =============================================================================
# Atomicity
# =============================================================================


class TestAtomicity:
    """Atomicity is provided by ``_write_parquet_file`` / ``_write_csv_file`` —
    the handler tests assert the contract still holds end-to-end."""

    def test_parquet_handler_write_crash_leaves_no_partial_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler: ParquetHandler = _make_parquet_handler(tmp_path)

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_parquet', _explode)

        with pytest.raises(RuntimeError, match='simulated crash'):
            handler.from_dataframe(_all_dtypes_frame())

        assert not handler.data_path.exists()

    def test_csv_handler_write_crash_leaves_no_partial_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler: CsvHandler = _make_csv_handler(tmp_path)

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_csv', _explode)

        with pytest.raises(RuntimeError, match='simulated crash'):
            handler.from_dataframe(pd.DataFrame({'id': [1]}))

        assert not handler.data_path.exists()


# =============================================================================
# Factory dispatch
# =============================================================================


class TestFactoryDispatch:
    def test_parquet_format_returns_parquet_handler(self, tmp_path: Path) -> None:
        config: OutputConfig = OutputConfig(
            format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
        )
        handler: StorageHandler = get_storage_handler(
            output_config=config,
            working_directory=tmp_path,
            resource_name=_RESOURCE_NAME,
        )
        assert isinstance(handler, ParquetHandler)

    def test_csv_format_returns_csv_handler(self, tmp_path: Path) -> None:
        config: OutputConfig = OutputConfig(format=OutputFormat.CSV, compression=None)
        handler: StorageHandler = get_storage_handler(
            output_config=config,
            working_directory=tmp_path,
            resource_name=_RESOURCE_NAME,
        )
        assert isinstance(handler, CsvHandler)

    def test_compression_threads_through_to_parquet_handler(
        self,
        tmp_path: Path,
    ) -> None:
        config: OutputConfig = OutputConfig(
            format=OutputFormat.PARQUET,
            compression=ParquetCompression.GZIP,
        )
        handler: StorageHandler = get_storage_handler(
            output_config=config,
            working_directory=tmp_path,
            resource_name=_RESOURCE_NAME,
        )
        assert isinstance(handler, ParquetHandler)
        # The compression value is private to the handler; verify it
        # round-trips end-to-end by writing and reading a real frame
        # under a non-default codec.
        handler.from_dataframe(_all_dtypes_frame())
        pd.testing.assert_frame_equal(handler.to_dataframe(), _all_dtypes_frame())

    def test_factory_returns_handler_satisfying_protocol_surface(
        self,
        tmp_path: Path,
    ) -> None:
        # Exercises every Protocol member at runtime so the structural
        # contract is checked end-to-end. The static (mypy) check on
        # the factory's return type is the other half of the guarantee.
        config: OutputConfig = OutputConfig(
            format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
        )
        handler: StorageHandler = get_storage_handler(
            output_config=config,
            working_directory=tmp_path,
            resource_name=_RESOURCE_NAME,
        )
        assert isinstance(handler.data_path, Path)
        assert isinstance(handler.metadata_path, Path)
        assert handler.read_metadata() is None
        handler.write_metadata(_example_metadata())
        handler.from_dataframe(_all_dtypes_frame())
        assert isinstance(handler.to_dataframe(), pd.DataFrame)
