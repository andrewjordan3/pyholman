# tests/_pipeline/test_processor.py
"""Smoke tests for :class:`ResourceProcessor`."""

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from pyholman._client import HolmanClient
from pyholman._clock import FrozenClock
from pyholman._config import OutputFormat, ParquetCompression, UserConfig
from pyholman._core import QueryInputBase, ResponseModel
from pyholman._core.constants import PACKAGE_NAME
from pyholman._endpoints.odometer import Odometer
from pyholman._endpoints.vehicles import Vehicle, VehiclesFilters
from pyholman._pipeline import (
    IncrementalStateCorruptedError,
    ResourceBundle,
    ResourceBundleBuilder,
    ResourcePreparer,
    ResourceProcessor,
    hash_filter_model,
)
from pyholman._storage import (
    CsvHandler,
    ParquetHandler,
    StorageMetadata,
    StorageRunMode,
)
from pyholman._storage.metadata import get_pyholman_version

__all__: list[str] = []


_FROZEN_INSTANT: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
_PRIOR_RECORD_UTC: datetime = _FROZEN_INSTANT - timedelta(days=10)


def _build_user_config(
    tmp_path: Path,
    *,
    resource_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
) -> UserConfig:
    payload: dict[str, Any] = {
        'credentials': {
            'client_id': 'my-client-id',
            'client_secret': 'test-secret-value',
        },
        'api': {'base_url': 'https://api.holman.solutions'},
        'fleet': {'lessee_codes': ['ABCD']},
        'working_directory': tmp_path,
        'incremental': {'lookback_days': 7},
        'resources': [resource_payload or {'name': 'vehicles'}],
    }
    if output_payload is not None:
        payload['output'] = output_payload
    return UserConfig.model_validate(payload)


def _build_bundle(
    tmp_path: Path,
    *,
    user_config: UserConfig | None = None,
    seed_metadata: StorageMetadata | None = None,
) -> ResourceBundle:
    config: UserConfig = user_config or _build_user_config(tmp_path)
    clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
    state_with_handler = (
        ResourceBundleBuilder(
            resource_config=config.resources[0],
            user_config=config,
            clock=clock,
        )
        .lookup_registry_entry()
        .construct_storage_handler()
    )
    if seed_metadata is not None:
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, ParquetHandler)
        seeded_handler.write_metadata(seed_metadata)
    bundle: ResourceBundle = (
        state_with_handler.compute_incremental_flags()
        .apply_window_floor()
        .build()
    )
    # The orchestrator stamps ``started_at_utc`` at the start of each
    # resource's processing loop. Tests bypass the orchestrator, so
    # the helper sets it directly to the test's frozen instant.
    bundle.started_at_utc = _FROZEN_INSTANT
    return bundle


def _make_mock_client(records: list[ResponseModel]) -> HolmanClient:
    """Mock client whose ``.collect(query)`` returns the supplied records."""
    mock_client: MagicMock = MagicMock(spec=HolmanClient)
    mock_client.collect.return_value = records
    return mock_client


# =============================================================================
# Dedup logging
# =============================================================================


class TestDedupLogging:
    """
    ``materialize_dataframe`` emits an INFO log line documenting the
    dedup result every time — even when nothing was removed — so a
    log reader can always tell that dedup ran. Without this line, the
    real ``contacts`` workload's 3860 → 772 drop reads as a mystery
    shrink.
    """

    @staticmethod
    @pytest.fixture
    def propagating_pyholman_logger(monkeypatch: pytest.MonkeyPatch) -> None:
        # Earlier tests in the run may have invoked the real
        # ``setup_logger`` which flips ``pyholman.propagate = False``.
        # That stops caplog (which attaches to the root logger) from
        # observing pyholman output. Force propagation back on for the
        # duration of these tests so the log lines we care about are
        # captured deterministically.
        package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
        monkeypatch.setattr(package_logger, 'propagate', True)

    @staticmethod
    def _dedup_message(
        caplog: pytest.LogCaptureFixture,
        resource_name: str,
    ) -> str:
        prefix: str = f'Resource {resource_name!r} deduplicated: '
        matching: list[str] = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith(prefix)
        ]
        assert len(matching) == 1, (
            f'expected exactly one dedup log line for {resource_name!r}, '
            f'got {matching!r}'
        )
        return matching[0]

    def test_dedup_log_reports_removed_rows_when_duplicates_present(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'odometer'},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        # Three identical records — drop_duplicates collapses to one.
        record: Odometer = Odometer.model_validate({'holmanVehicleNumber': 'V1'})
        client: HolmanClient = _make_mock_client([record, record, record])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            ResourceProcessor(
                bundle=bundle, client=client, clock=clock
            ).execute_query().materialize_dataframe()

        message: str = self._dedup_message(caplog, 'odometer')
        # Pin the structured fields so the user-visible shape doesn't
        # silently drift.
        assert 'input_rows=3' in message
        assert 'output_rows=1' in message
        assert 'removed_rows=2' in message
        assert re.search(r'duplicate_rate=66\.6\d%', message)

    def test_dedup_log_emitted_even_when_nothing_removed(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'odometer'},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        client: HolmanClient = _make_mock_client(
            [
                Odometer.model_validate({'holmanVehicleNumber': 'V1'}),
                Odometer.model_validate({'holmanVehicleNumber': 'V2'}),
            ]
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            ResourceProcessor(
                bundle=bundle, client=client, clock=clock
            ).execute_query().materialize_dataframe()

        message: str = self._dedup_message(caplog, 'odometer')
        assert 'input_rows=2' in message
        assert 'output_rows=2' in message
        assert 'removed_rows=0' in message
        assert 'duplicate_rate=0.00%' in message

    def test_dedup_log_handles_empty_input_without_division_by_zero(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        propagating_pyholman_logger: None,
    ) -> None:
        del propagating_pyholman_logger
        # Empty record list passes through dedup as an empty frame.
        # The dedup line still reports zero/zero — confirming dedup
        # ran — and reports a 0.00% rate without raising
        # ZeroDivisionError.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'odometer'},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        client: HolmanClient = _make_mock_client([])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            ResourceProcessor(
                bundle=bundle, client=client, clock=clock
            ).execute_query().materialize_dataframe()

        message: str = self._dedup_message(caplog, 'odometer')
        assert 'input_rows=0' in message
        assert 'output_rows=0' in message
        assert 'removed_rows=0' in message
        assert 'duplicate_rate=0.00%' in message


# =============================================================================
# Snapshot resource happy path
# =============================================================================


class TestSnapshotPersist:
    def test_full_chain_writes_parquet_and_metadata(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path, resource_payload={'name': 'odometer'}
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        # Odometer's response model is tolerant; build a single record
        # by passing only what the model requires.
        record: Odometer = Odometer.model_validate({'holmanVehicleNumber': 'V1'})
        client: HolmanClient = _make_mock_client([record])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        (
            ResourceProcessor(bundle=bundle, client=client, clock=clock)
            .execute_query()
            .materialize_dataframe()
            .merge_incremental()
            .persist()
        )

        assert bundle.storage_handler.data_path.exists()
        assert bundle.storage_handler.metadata_path.exists()

        # The persisted metadata reflects a snapshot run. Snapshot
        # endpoints have no per-record watermark, so persist routes
        # through :meth:`StorageMetadata.for_snapshot` and the resulting
        # metadata carries ``most_recent_record_utc=None`` and
        # ``run_mode=FULL_REFRESH``.
        metadata: StorageMetadata | None = bundle.storage_handler.read_metadata()
        assert metadata is not None
        assert metadata.endpoint == 'odometer'
        assert metadata.run_mode == StorageRunMode.FULL_REFRESH
        assert metadata.most_recent_record_utc is None
        assert metadata.record_count == 1


# =============================================================================
# Incremental first-time happy path
# =============================================================================


class TestFirstTimeIncrementalPersist:
    def test_full_chain_records_incremental_run_mode(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V1',
                'lastChangeDate': _PRIOR_RECORD_UTC.isoformat(),
            }
        )
        client: HolmanClient = _make_mock_client([record])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        (
            ResourceProcessor(bundle=bundle, client=client, clock=clock)
            .execute_query()
            .materialize_dataframe()
            .merge_incremental()
            .persist()
        )

        metadata: StorageMetadata | None = bundle.storage_handler.read_metadata()
        assert metadata is not None
        # Run mode follows configuration, not effect: this is a
        # first-time-incremental run, but it still reports as
        # INCREMENTAL because the resource is configured that way.
        assert metadata.run_mode == StorageRunMode.INCREMENTAL
        # The ``most_recent_record_utc`` anchor comes from the (only)
        # record's watermark.
        assert metadata.most_recent_record_utc == _PRIOR_RECORD_UTC


# =============================================================================
# Incremental-with-prior happy path
# =============================================================================


class TestIncrementalWithPriorPersist:
    def test_merge_replaces_window_with_new_rows(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        # Seed a prior data file. We mock the on-disk dataframe via
        # the storage handler API so the merge step has something to
        # load.
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        state_with_handler = (
            ResourceBundleBuilder(
                resource_config=config.resources[0],
                user_config=config,
                clock=clock,
            )
            .lookup_registry_entry()
            .construct_storage_handler()
        )
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, ParquetHandler)

        # Prior data: one record at the "old" watermark, well before
        # the window we're about to refresh.
        old_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_OLD',
                'lastChangeDate': (_PRIOR_RECORD_UTC - timedelta(days=30)).isoformat(),
            }
        )
        prior_frame = Vehicle.records_to_dataframe([old_record])
        seeded_handler.from_dataframe(prior_frame)
        seeded_handler.write_metadata(
            StorageMetadata(
                endpoint='vehicles',
                pyholman_version=get_pyholman_version(),
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=_FROZEN_INSTANT - timedelta(days=1),
                run_completed_utc=_FROZEN_INSTANT - timedelta(days=1),
                most_recent_record_utc=_PRIOR_RECORD_UTC,
                record_count=1,
                output_format=OutputFormat.PARQUET,
                compression=ParquetCompression.SNAPPY,
                filters_hash=hash_filter_model(VehiclesFilters()),
            )
        )

        bundle: ResourceBundle = (
            state_with_handler.compute_incremental_flags()
            .apply_window_floor()
            .build()
        )
        bundle.started_at_utc = _FROZEN_INSTANT
        ResourcePreparer(bundle=bundle).resolve_window().build_query()

        # New record well inside the resolved window — merging must
        # keep the old (outside-window) record and replace whatever
        # was inside the window.
        new_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_NEW',
                'lastChangeDate': _FROZEN_INSTANT.isoformat(),
            }
        )
        client: HolmanClient = _make_mock_client([new_record])

        (
            ResourceProcessor(bundle=bundle, client=client, clock=clock)
            .execute_query()
            .materialize_dataframe()
            .merge_incremental()
            .persist()
        )

        # Read the persisted file back: both rows survive (old kept
        # because outside window; new added).
        restored = bundle.storage_handler.to_dataframe()
        assert len(restored) == 2
        assert set(restored['holman_vehicle_number'].tolist()) == {'V_OLD', 'V_NEW'}


# =============================================================================
# CSV incremental: dtype coercion of the watermark column on read
# =============================================================================


class TestCsvIncrementalWatermarkCoercion:
    """
    CSV is lossy for dtypes — :func:`pandas.read_csv` returns the
    watermark column as object/str, not datetime — so
    :meth:`ResourceProcessor.merge_incremental` must coerce the
    column back to tz-aware UTC datetime before
    :func:`replace_window` runs its window comparison. Without the
    coercion the merge step raises ``TypeError: '<' not supported
    between instances of 'str' and 'datetime.datetime'``.
    """

    def test_lossy_csv_roundtrip_documents_str_watermark_dtype(
        self,
        tmp_path: Path,
    ) -> None:
        # Pin the lossy contract that motivates the coercion: a CSV
        # written with a tz-aware datetime column round-trips back as
        # object/str. If pandas ever changes this, the coercion step
        # may become unnecessary — but we want a loud signal first.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
            output_payload={'format': 'csv'},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        state_with_handler = (
            ResourceBundleBuilder(
                resource_config=config.resources[0],
                user_config=config,
                clock=clock,
            )
            .lookup_registry_entry()
            .construct_storage_handler()
        )
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, CsvHandler)

        record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_OLD',
                'lastChangeDate': _PRIOR_RECORD_UTC.isoformat(),
            }
        )
        seeded_handler.from_dataframe(Vehicle.records_to_dataframe([record]))

        restored = seeded_handler.to_dataframe()
        # The watermark column comes back as object/string (the exact
        # dtype depends on the pandas version); the key invariant for
        # the merge step is that it is not datetime-typed and so the
        # ``< window_start`` comparison would raise ``TypeError``.
        # This is the lossy roundtrip the coercion in
        # ``merge_incremental`` is there to repair.
        assert not pd.api.types.is_datetime64_any_dtype(
            restored['last_change_date']
        )

    def test_full_chain_succeeds_under_csv_incremental_with_prior(
        self,
        tmp_path: Path,
    ) -> None:
        # End-to-end regression: the same workflow that worked under
        # Parquet must also work under CSV. Before the coercion fix,
        # this raised ``TypeError`` at ``replace_window``.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
            output_payload={'format': 'csv'},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        state_with_handler = (
            ResourceBundleBuilder(
                resource_config=config.resources[0],
                user_config=config,
                clock=clock,
            )
            .lookup_registry_entry()
            .construct_storage_handler()
        )
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, CsvHandler)

        old_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_OLD',
                'lastChangeDate': (_PRIOR_RECORD_UTC - timedelta(days=30)).isoformat(),
            }
        )
        seeded_handler.from_dataframe(Vehicle.records_to_dataframe([old_record]))
        seeded_handler.write_metadata(
            StorageMetadata(
                endpoint='vehicles',
                pyholman_version=get_pyholman_version(),
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=_FROZEN_INSTANT - timedelta(days=1),
                run_completed_utc=_FROZEN_INSTANT - timedelta(days=1),
                most_recent_record_utc=_PRIOR_RECORD_UTC,
                record_count=1,
                output_format=OutputFormat.CSV,
                compression=None,
                filters_hash=hash_filter_model(VehiclesFilters()),
            )
        )

        bundle: ResourceBundle = (
            state_with_handler.compute_incremental_flags()
            .apply_window_floor()
            .build()
        )
        bundle.started_at_utc = _FROZEN_INSTANT
        ResourcePreparer(bundle=bundle).resolve_window().build_query()

        new_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_NEW',
                'lastChangeDate': _FROZEN_INSTANT.isoformat(),
            }
        )
        client: HolmanClient = _make_mock_client([new_record])

        (
            ResourceProcessor(bundle=bundle, client=client, clock=clock)
            .execute_query()
            .materialize_dataframe()
            .merge_incremental()
            .persist()
        )

        restored = bundle.storage_handler.to_dataframe()
        assert len(restored) == 2
        assert set(restored['holman_vehicle_number'].tolist()) == {'V_OLD', 'V_NEW'}

    def test_unparseable_watermark_raises_typed_corruption_error(
        self,
        tmp_path: Path,
    ) -> None:
        # A CSV whose watermark column has been hand-edited to an
        # un-parseable value should not silently rescue the row (which
        # would keep it stuck forever) — it should raise a typed
        # exception that names the file and prescribes the recovery.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
            output_payload={'format': 'csv'},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)
        state_with_handler = (
            ResourceBundleBuilder(
                resource_config=config.resources[0],
                user_config=config,
                clock=clock,
            )
            .lookup_registry_entry()
            .construct_storage_handler()
        )
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, CsvHandler)

        valid_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_OLD',
                'lastChangeDate': (_PRIOR_RECORD_UTC - timedelta(days=30)).isoformat(),
            }
        )
        seeded_handler.from_dataframe(Vehicle.records_to_dataframe([valid_record]))

        # Hand-edit the on-disk CSV to corrupt the existing row's
        # watermark. Round-trip through pandas to guarantee the row
        # shape stays consistent, then overwrite a single value with a
        # non-parseable string. The failure must come from the dtype
        # coercion, not from CSV parsing.
        data_path: Path = seeded_handler.data_path
        corrupted_frame: pd.DataFrame = pd.read_csv(data_path)
        corrupted_frame.loc[0, 'last_change_date'] = 'this-is-not-a-datetime'
        corrupted_frame.to_csv(data_path, index=False)

        seeded_handler.write_metadata(
            StorageMetadata(
                endpoint='vehicles',
                pyholman_version=get_pyholman_version(),
                run_mode=StorageRunMode.INCREMENTAL,
                run_started_utc=_FROZEN_INSTANT - timedelta(days=1),
                run_completed_utc=_FROZEN_INSTANT - timedelta(days=1),
                most_recent_record_utc=_PRIOR_RECORD_UTC,
                record_count=1,
                output_format=OutputFormat.CSV,
                compression=None,
                filters_hash=hash_filter_model(VehiclesFilters()),
            )
        )

        bundle: ResourceBundle = (
            state_with_handler.compute_incremental_flags()
            .apply_window_floor()
            .build()
        )
        bundle.started_at_utc = _FROZEN_INSTANT
        ResourcePreparer(bundle=bundle).resolve_window().build_query()

        new_record: Vehicle = Vehicle.model_validate(
            {
                'holmanVehicleNumber': 'V_NEW',
                'lastChangeDate': _FROZEN_INSTANT.isoformat(),
            }
        )
        client: HolmanClient = _make_mock_client([new_record])
        processor: ResourceProcessor = ResourceProcessor(
            bundle=bundle, client=client, clock=clock
        )
        processor.execute_query().materialize_dataframe()

        with pytest.raises(IncrementalStateCorruptedError) as exc_info:
            processor.merge_incremental()

        # Message must name the resource, the file path, and the column
        # so the user can find and recover the affected file.
        message: str = str(exc_info.value)
        assert 'vehicles' in message
        assert str(bundle.storage_handler.data_path) in message
        assert 'last_change_date' in message
        assert 'incremental: false' in message
        # And the structured attributes are populated for programmatic
        # callers that want to pattern-match.
        assert exc_info.value.resource_name == 'vehicles'
        assert exc_info.value.file_path == bundle.storage_handler.data_path
        assert exc_info.value.watermark_column == 'last_change_date'


# =============================================================================
# Empty result raises at persist
# =============================================================================


class TestEmptyResultRaises:
    def test_zero_records_raises_at_persist(self, tmp_path: Path) -> None:
        # Empty results are a locked failure mode — the storage handler
        # rejects empty writes upstream, and ``persist`` surfaces that
        # rejection as the failure condition for an empty pull.
        config: UserConfig = _build_user_config(
            tmp_path, resource_payload={'name': 'vehicles', 'incremental': True}
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        ResourcePreparer(bundle=bundle).build_query()

        client: HolmanClient = _make_mock_client([])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        processor: ResourceProcessor = ResourceProcessor(
            bundle=bundle, client=client, clock=clock
        )
        processor.execute_query().materialize_dataframe().merge_incremental()

        with pytest.raises(ValueError, match='empty'):
            processor.persist()


# =============================================================================
# Ordering: missing prerequisites raise
# =============================================================================


class TestMissingPrerequisites:
    def test_execute_query_without_built_query_raises(self, tmp_path: Path) -> None:
        bundle: ResourceBundle = _build_bundle(tmp_path)
        client: HolmanClient = _make_mock_client([])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        with pytest.raises(RuntimeError, match='build_query'):
            ResourceProcessor(bundle=bundle, client=client, clock=clock).execute_query()

    def test_materialize_without_records_raises(self, tmp_path: Path) -> None:
        bundle: ResourceBundle = _build_bundle(tmp_path)
        # Set ``query`` so ``execute_query`` is bypassed; clear records
        # to force the dependency check in ``materialize_dataframe``.
        bundle.query = MagicMock(spec=QueryInputBase)
        bundle.records = None
        client: HolmanClient = _make_mock_client([])
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        with pytest.raises(RuntimeError, match='execute_query'):
            ResourceProcessor(
                bundle=bundle, client=client, clock=clock
            ).materialize_dataframe()
