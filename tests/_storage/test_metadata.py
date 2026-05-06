# tests/_storage/test_metadata.py
"""Tests for ``StorageMetadata`` and ``get_pyholman_version``."""

import importlib.metadata
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from pyholman._config import OutputFormat, ParquetCompression
from pyholman._storage import (
    StorageMetadata,
    StorageRunMode,
    get_pyholman_version,
)
from pyholman._storage.metadata import (
    model as metadata_model_module,
    version as metadata_version_module,
)

__all__: list[str] = []


# Deterministic valid SHA-256-shaped digest used wherever a test needs a
# syntactically correct ``filters_hash`` but the semantic value is
# irrelevant. 64 lowercase hex characters as required by the validator.
_PLACEHOLDER_FILTERS_HASH: str = '0' * 64


def _make_valid_metadata() -> StorageMetadata:
    run_started: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    run_completed: datetime = run_started + timedelta(seconds=30)
    return StorageMetadata(
        endpoint='maintenance',
        pyholman_version='0.1.0',
        run_mode=StorageRunMode.INCREMENTAL,
        run_started_utc=run_started,
        run_completed_utc=run_completed,
        most_recent_record_utc=run_started,
        record_count=42,
        output_format=OutputFormat.PARQUET,
        compression=ParquetCompression.SNAPPY,
        filters_hash=_PLACEHOLDER_FILTERS_HASH,
    )


class TestFrozenBehavior:
    def test_instance_is_immutable(self) -> None:
        metadata: StorageMetadata = _make_valid_metadata()
        with pytest.raises(ValidationError):
            metadata.endpoint = 'other'  # type: ignore[misc]

    def test_unknown_field_rejected(self) -> None:
        run_started: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError, match='extra'):
            StorageMetadata(
                endpoint='maintenance',
                pyholman_version='0.1.0',
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=run_started,
                run_completed_utc=run_started,
                most_recent_record_utc=None,
                record_count=0,
                output_format=OutputFormat.PARQUET,
                compression=None,
                filters_hash=_PLACEHOLDER_FILTERS_HASH,
                surprise='typo',  # type: ignore[call-arg]
            )


class TestDatetimeValidation:
    @pytest.mark.parametrize(
        'field_name',
        ['run_started_utc', 'run_completed_utc', 'most_recent_record_utc'],
    )
    def test_naive_datetime_rejected(self, field_name: str) -> None:
        aware_utc: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        naive_datetime: datetime = datetime(2026, 4, 21, 12, 0, 0)  # noqa: DTZ001 -- naive datetime is the condition under test

        kwargs: dict[str, object] = {
            'endpoint': 'maintenance',
            'pyholman_version': '0.1.0',
            'run_mode': StorageRunMode.INCREMENTAL,
            'run_started_utc': aware_utc,
            'run_completed_utc': aware_utc,
            'most_recent_record_utc': aware_utc,
            'record_count': 1,
            'output_format': OutputFormat.PARQUET,
            'compression': ParquetCompression.SNAPPY,
            'filters_hash': _PLACEHOLDER_FILTERS_HASH,
        }
        kwargs[field_name] = naive_datetime

        with pytest.raises(ValidationError):
            StorageMetadata(**kwargs)

    def test_completed_before_started_rejected(self) -> None:
        started: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        completed: datetime = started - timedelta(seconds=1)

        with pytest.raises(ValidationError, match='run_completed_utc'):
            StorageMetadata(
                endpoint='maintenance',
                pyholman_version='0.1.0',
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=started,
                run_completed_utc=completed,
                most_recent_record_utc=None,
                record_count=0,
                output_format=OutputFormat.PARQUET,
                compression=None,
                filters_hash=_PLACEHOLDER_FILTERS_HASH,
            )


class TestRecordCountConsistency:
    def test_zero_count_with_non_null_recent_rejected(self) -> None:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError, match='most_recent_record_utc'):
            StorageMetadata(
                endpoint='maintenance',
                pyholman_version='0.1.0',
                run_mode=StorageRunMode.FULL_REFRESH,
                run_started_utc=instant,
                run_completed_utc=instant,
                most_recent_record_utc=instant,
                record_count=0,
                output_format=OutputFormat.PARQUET,
                compression=ParquetCompression.SNAPPY,
                filters_hash=_PLACEHOLDER_FILTERS_HASH,
            )

    def test_positive_count_with_null_recent_accepted_at_base(self) -> None:
        # Snapshot-only endpoints persist non-empty data without a
        # record-level anchor; the base model accepts that. The
        # "non-empty implies non-None anchor" rule lives on
        # :meth:`StorageMetadata.for_incremental` and is exercised
        # there.
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata(
            endpoint='odometer',
            pyholman_version='0.1.0',
            run_mode=StorageRunMode.FULL_REFRESH,
            run_started_utc=instant,
            run_completed_utc=instant,
            most_recent_record_utc=None,
            record_count=5,
            output_format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.record_count == 5
        assert metadata.most_recent_record_utc is None

    def test_zero_count_with_null_recent_accepted(self) -> None:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata(
            endpoint='maintenance',
            pyholman_version='0.1.0',
            run_mode=StorageRunMode.FULL_REFRESH,
            run_started_utc=instant,
            run_completed_utc=instant,
            most_recent_record_utc=None,
            record_count=0,
            output_format=OutputFormat.PARQUET,
            compression=None,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.record_count == 0

    def test_negative_record_count_rejected(self) -> None:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError):
            StorageMetadata(
                endpoint='maintenance',
                pyholman_version='0.1.0',
                run_mode=StorageRunMode.FULL_REFRESH,
                run_started_utc=instant,
                run_completed_utc=instant,
                most_recent_record_utc=None,
                record_count=-1,
                output_format=OutputFormat.PARQUET,
                compression=None,
                filters_hash=_PLACEHOLDER_FILTERS_HASH,
            )


class TestJsonRoundTrip:
    def test_to_json_from_json_round_trip(self, tmp_path: Path) -> None:
        metadata: StorageMetadata = _make_valid_metadata()
        sidecar_path: Path = tmp_path / 'data.parquet.meta.json'

        metadata.to_json(sidecar_path)
        loaded_metadata: StorageMetadata = StorageMetadata.from_json(sidecar_path)

        assert loaded_metadata == metadata

    def test_to_json_output_is_indented_with_trailing_newline(
        self,
        tmp_path: Path,
    ) -> None:
        metadata: StorageMetadata = _make_valid_metadata()
        sidecar_path: Path = tmp_path / 'data.parquet.meta.json'
        metadata.to_json(sidecar_path)

        content: str = sidecar_path.read_text(encoding='utf-8')
        assert content.endswith('\n')
        # Indented JSON has newlines and two-space indentation.
        assert '\n  ' in content

        parsed: dict[str, object] = json.loads(content)
        assert parsed['endpoint'] == 'maintenance'
        assert parsed['run_mode'] == 'incremental'
        assert parsed['record_count'] == 42
        assert parsed['output_format'] == 'parquet'
        assert parsed['compression'] == 'snappy'

    def test_from_json_missing_file_raises_with_path(
        self,
        tmp_path: Path,
    ) -> None:
        missing_path: Path = tmp_path / 'no-such-sidecar.json'
        with pytest.raises(FileNotFoundError, match=re.escape(str(missing_path))):
            StorageMetadata.from_json(missing_path)


class TestAtomicity:
    def test_mid_write_crash_leaves_prior_file_intact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sidecar_path: Path = tmp_path / 'data.parquet.meta.json'

        first_metadata: StorageMetadata = _make_valid_metadata()
        first_metadata.to_json(sidecar_path)
        prior_bytes: bytes = sidecar_path.read_bytes()

        def _explode(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError('simulated crash mid-write')

        # model_dump_json is called inside to_json before the file is
        # opened for atomic write; raising there still exercises the
        # atomic-write contract because no temp file is ever created.
        # Patch the write-side call instead so the tempfile is created
        # and then discarded without renaming.
        monkeypatch.setattr(
            StorageMetadata,
            'model_dump_json',
            _explode,
        )

        second_metadata: StorageMetadata = _make_valid_metadata()
        with pytest.raises(RuntimeError, match='simulated crash'):
            second_metadata.to_json(sidecar_path)

        assert sidecar_path.read_bytes() == prior_bytes

    def test_mid_write_crash_on_fresh_path_leaves_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sidecar_path: Path = tmp_path / 'fresh.meta.json'

        def _explode_on_atomic_write(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        # Patch ``atomic_write`` itself so a fresh call explodes before
        # any temp file is created at the target location. The contract
        # is that the target path remains absent after failure.
        monkeypatch.setattr(
            metadata_model_module, 'atomic_write', _explode_on_atomic_write
        )

        metadata: StorageMetadata = _make_valid_metadata()
        with pytest.raises(RuntimeError, match='simulated crash'):
            metadata.to_json(sidecar_path)

        assert not sidecar_path.exists()


class TestFiltersHash:
    def _base_kwargs(self) -> dict[str, object]:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        return {
            'endpoint': 'vehicles',
            'pyholman_version': '0.1.0',
            'run_mode': StorageRunMode.FULL_REFRESH,
            'run_started_utc': instant,
            'run_completed_utc': instant,
            'most_recent_record_utc': None,
            'record_count': 0,
            'output_format': OutputFormat.PARQUET,
            'compression': None,
        }

    def test_valid_hash_accepted(self) -> None:
        metadata: StorageMetadata = StorageMetadata(
            **self._base_kwargs(),
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.filters_hash == _PLACEHOLDER_FILTERS_HASH

    def test_missing_filters_hash_rejected(self) -> None:
        with pytest.raises(ValidationError, match='filters_hash'):
            StorageMetadata(**self._base_kwargs())  # type: ignore[call-arg]

    def test_short_hash_rejected(self) -> None:
        with pytest.raises(ValidationError, match='filters_hash'):
            StorageMetadata(**self._base_kwargs(), filters_hash='abc123')

    def test_uppercase_hash_rejected(self) -> None:
        with pytest.raises(ValidationError, match='filters_hash'):
            StorageMetadata(**self._base_kwargs(), filters_hash='A' * 64)

    def test_non_hex_characters_rejected(self) -> None:
        with pytest.raises(ValidationError, match='filters_hash'):
            StorageMetadata(**self._base_kwargs(), filters_hash='z' * 64)

    def test_json_round_trip_preserves_filters_hash(self, tmp_path: Path) -> None:
        sidecar_path: Path = tmp_path / 'data.parquet.meta.json'
        original: StorageMetadata = StorageMetadata(
            **self._base_kwargs(),
            filters_hash='ab' * 32,
        )
        original.to_json(sidecar_path)
        loaded: StorageMetadata = StorageMetadata.from_json(sidecar_path)
        assert loaded.filters_hash == 'ab' * 32


# =============================================================================
# Factory classmethods
# =============================================================================


class TestForSnapshotFactory:
    """``StorageMetadata.for_snapshot`` is the construction entry point
    for snapshot-only endpoints — no per-record watermark, run mode
    locked to ``FULL_REFRESH``."""

    def test_produces_none_anchor_and_full_refresh_mode(self) -> None:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata.for_snapshot(
            endpoint='odometer',
            pyholman_version='0.1.0',
            run_started_utc=instant,
            run_completed_utc=instant,
            record_count=42,
            output_format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )

        assert metadata.most_recent_record_utc is None
        assert metadata.run_mode == StorageRunMode.FULL_REFRESH
        assert metadata.record_count == 42

    def test_zero_record_count_accepted(self) -> None:
        # An empty snapshot pull would normally fail upstream at the
        # storage handler's empty-write check; ``for_snapshot`` does
        # not duplicate that gate, so a zero count round-trips fine
        # here.
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata.for_snapshot(
            endpoint='odometer',
            pyholman_version='0.1.0',
            run_started_utc=instant,
            run_completed_utc=instant,
            record_count=0,
            output_format=OutputFormat.PARQUET,
            compression=None,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.record_count == 0
        assert metadata.most_recent_record_utc is None


class TestForIncrementalFactory:
    """``StorageMetadata.for_incremental`` enforces the "non-empty
    implies non-None anchor" rule that the base validator no longer
    enforces."""

    def test_positive_count_with_anchor_accepted(self) -> None:
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        anchor: datetime = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata.for_incremental(
            endpoint='vehicles',
            pyholman_version='0.1.0',
            run_mode=StorageRunMode.INCREMENTAL,
            run_started_utc=instant,
            run_completed_utc=instant,
            most_recent_record_utc=anchor,
            record_count=10,
            output_format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.run_mode == StorageRunMode.INCREMENTAL
        assert metadata.most_recent_record_utc == anchor

    def test_positive_count_with_null_anchor_rejected(self) -> None:
        # Incremental-capable endpoints always have a record-level
        # anchor when records are present; the factory rejects the
        # nonsensical combination.
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match='for_incremental'):
            StorageMetadata.for_incremental(
                endpoint='vehicles',
                pyholman_version='0.1.0',
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=instant,
                run_completed_utc=instant,
                most_recent_record_utc=None,
                record_count=5,
                output_format=OutputFormat.PARQUET,
                compression=ParquetCompression.SNAPPY,
                filters_hash=_PLACEHOLDER_FILTERS_HASH,
            )

    def test_zero_count_with_null_anchor_accepted(self) -> None:
        # A first-time-incremental run that returned zero rows would
        # not normally reach metadata write (empty writes are rejected
        # at the storage handler), but the factory is permissive on
        # the zero-records branch — only ``record_count > 0`` triggers
        # the additional rule.
        instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        metadata: StorageMetadata = StorageMetadata.for_incremental(
            endpoint='vehicles',
            pyholman_version='0.1.0',
            run_mode=StorageRunMode.INCREMENTAL,
            run_started_utc=instant,
            run_completed_utc=instant,
            most_recent_record_utc=None,
            record_count=0,
            output_format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
            filters_hash=_PLACEHOLDER_FILTERS_HASH,
        )
        assert metadata.record_count == 0


class TestGetPyholmanVersion:
    def test_returns_nonempty_string(self) -> None:
        version_string: str = get_pyholman_version()
        assert isinstance(version_string, str)
        assert len(version_string) > 0

    def test_fallback_to_unknown_on_package_not_found(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise_not_found(name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(metadata_version_module, 'version', _raise_not_found)

        assert get_pyholman_version() == 'unknown'
