# tests/_pipeline/test_builder.py
"""Smoke tests for :class:`ResourceBundleBuilder`'s fluent chain."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pyholman._clock import FrozenClock
from pyholman._config import (
    IncrementalConfig,
    OutputFormat,
    ParquetCompression,
    UserConfig,
)
from pyholman._pipeline import ResourceBundle, ResourceBundleBuilder
from pyholman._storage import (
    ParquetHandler,
    StorageMetadata,
    StorageRunMode,
)
from pyholman._storage.metadata import get_pyholman_version

__all__: list[str] = []


_FROZEN_INSTANT: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
_PLACEHOLDER_FILTERS_HASH: str = '0' * 64


def _build_user_config(
    tmp_path: Path,
    *,
    earliest_date: date | None = None,
    resource_payload: dict[str, Any] | None = None,
) -> UserConfig:
    incremental_payload: dict[str, Any] = {'lookback_days': 7}
    if earliest_date is not None:
        incremental_payload['earliest_date'] = earliest_date.isoformat()
    return UserConfig.model_validate(
        {
            'credentials': {
                'client_id': 'my-client-id',
                'client_secret': 'test-secret-value',
            },
            'api': {'base_url': 'https://api.holman.solutions'},
            'fleet': {'lessee_codes': ['ABCD']},
            'working_directory': tmp_path,
            'incremental': incremental_payload,
            'resources': [resource_payload or {'name': 'vehicles'}],
        }
    )


def _seed_prior_metadata(
    *,
    storage_handler: ParquetHandler,
    endpoint: str,
    most_recent: datetime,
) -> None:
    """Write a valid metadata sidecar for ``storage_handler``'s resource."""
    instant: datetime = _FROZEN_INSTANT - timedelta(days=1)
    metadata: StorageMetadata = StorageMetadata(
        endpoint=endpoint,
        pyholman_version=get_pyholman_version(),
        run_mode=StorageRunMode.INCREMENTAL,
        run_started_utc=instant,
        run_completed_utc=instant,
        most_recent_record_utc=most_recent,
        record_count=1,
        output_format=OutputFormat.PARQUET,
        compression=ParquetCompression.SNAPPY,
        filters_hash=_PLACEHOLDER_FILTERS_HASH,
    )
    storage_handler.write_metadata(metadata)


def _full_chain(builder: ResourceBundleBuilder) -> ResourceBundle:
    return (
        builder.lookup_registry_entry()
        .construct_storage_handler()
        .compute_incremental_flags()
        .apply_window_floor()
        .build()
    )


class TestSnapshotResource:
    def test_full_chain_yields_snapshot_bundle(self, tmp_path: Path) -> None:
        # Odometer is snapshot-only; a post-validator on
        # ``OdometerResourceConfig`` enforces ``incremental=False``.
        # The bundle must reflect that with both flags False and no
        # window floor.
        user_config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'odometer'},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        bundle: ResourceBundle = _full_chain(
            ResourceBundleBuilder(
                resource_config=user_config.resources[0],
                user_config=user_config,
                clock=clock,
            )
        )

        assert bundle.resource_name == 'odometer'
        assert bundle.is_incremental is False
        assert bundle.is_incremental_with_prior is False
        assert bundle.window_start is None
        # ``started_at_utc`` is left ``None`` by the builder; the
        # orchestrator's per-resource processing loop sets it before
        # the processor chain runs.
        assert bundle.started_at_utc is None


class TestFirstTimeIncrementalResource:
    def test_no_prior_no_floor_window_start_is_none(self, tmp_path: Path) -> None:
        user_config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        bundle: ResourceBundle = _full_chain(
            ResourceBundleBuilder(
                resource_config=user_config.resources[0],
                user_config=user_config,
                clock=clock,
            )
        )

        assert bundle.is_incremental is True
        assert bundle.is_incremental_with_prior is False
        assert bundle.window_start is None

    def test_no_prior_with_floor_window_start_is_floor_at_utc_midnight(
        self,
        tmp_path: Path,
    ) -> None:
        floor_date: date = date(2026, 1, 1)
        user_config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=floor_date,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        bundle: ResourceBundle = _full_chain(
            ResourceBundleBuilder(
                resource_config=user_config.resources[0],
                user_config=user_config,
                clock=clock,
            )
        )

        assert bundle.is_incremental is True
        assert bundle.is_incremental_with_prior is False
        assert bundle.window_start == datetime(2026, 1, 1, tzinfo=UTC)


class TestIncrementalWithPriorResource:
    def test_prior_metadata_lights_up_with_prior_flag(self, tmp_path: Path) -> None:
        user_config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        # Seed a prior metadata sidecar so the builder's metadata read
        # returns a non-None value. We capture the post-handler state
        # to reach the constructed handler before the metadata read
        # in ``compute_incremental_flags``.
        state_with_handler = (
            ResourceBundleBuilder(
                resource_config=user_config.resources[0],
                user_config=user_config,
                clock=clock,
            )
            .lookup_registry_entry()
            .construct_storage_handler()
        )
        seeded_handler = state_with_handler.storage_handler
        assert isinstance(seeded_handler, ParquetHandler)
        _seed_prior_metadata(
            storage_handler=seeded_handler,
            endpoint='vehicles',
            most_recent=_FROZEN_INSTANT - timedelta(days=14),
        )

        bundle: ResourceBundle = (
            state_with_handler.compute_incremental_flags()
            .apply_window_floor()
            .build()
        )

        assert bundle.is_incremental is True
        assert bundle.is_incremental_with_prior is True
        # ``apply_window_floor`` set window_start from the (absent)
        # ``earliest_date`` config — None at this point. The preparer's
        # ``resolve_window`` is what shifts it for incremental-with-prior.
        assert bundle.window_start is None


class TestBuilderUnusedConfig:
    """Pin that an unused ``IncrementalConfig`` does not affect the chain."""

    def test_default_incremental_config_is_accepted(self, tmp_path: Path) -> None:
        # The builder reads ``user_config.incremental.earliest_date``
        # in ``apply_window_floor``; the default of ``None`` means the
        # window stays at None for non-incremental resources too.
        user_config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'odometer'},
        )
        assert user_config.incremental == IncrementalConfig(lookback_days=7)
        clock: FrozenClock = FrozenClock(start_time_utc=_FROZEN_INSTANT)

        bundle: ResourceBundle = _full_chain(
            ResourceBundleBuilder(
                resource_config=user_config.resources[0],
                user_config=user_config,
                clock=clock,
            )
        )
        assert bundle.window_start is None
