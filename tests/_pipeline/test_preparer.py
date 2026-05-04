# tests/_pipeline/test_preparer.py
"""Smoke tests for :class:`ResourcePreparer`."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from pyholman._clock import FrozenClock
from pyholman._config import (
    OutputFormat,
    ParquetCompression,
    UserConfig,
)
from pyholman._endpoints.vehicles import VehiclesFilters, VehiclesQuery
from pyholman._pipeline import (
    FilterHashMismatchError,
    ResourceBundle,
    ResourceBundleBuilder,
    ResourcePreparer,
    hash_filter_model,
)
from pyholman._storage import (
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
    lookback_days: int = 7,
    earliest_date: date | None = None,
    resource_payload: dict[str, Any] | None = None,
) -> UserConfig:
    incremental_payload: dict[str, Any] = {'lookback_days': lookback_days}
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
    return (
        state_with_handler.compute_incremental_flags()
        .apply_window_floor()
        .build()
    )


def _metadata_for(
    *,
    most_recent: datetime,
    filters_hash: str,
) -> StorageMetadata:
    return StorageMetadata(
        endpoint='vehicles',
        pyholman_version=get_pyholman_version(),
        run_mode=StorageRunMode.INCREMENTAL,
        run_started_utc=_FROZEN_INSTANT - timedelta(days=1),
        run_completed_utc=_FROZEN_INSTANT - timedelta(days=1),
        most_recent_record_utc=most_recent,
        record_count=1,
        output_format=OutputFormat.PARQUET,
        compression=ParquetCompression.SNAPPY,
        filters_hash=filters_hash,
    )


# =============================================================================
# verify_filter_hash
# =============================================================================


class TestVerifyFilterHash:
    def test_snapshot_short_circuits(self, tmp_path: Path) -> None:
        # Snapshot resources skip the check; no metadata is read, no
        # exception is raised.
        config: UserConfig = _build_user_config(
            tmp_path, resource_payload={'name': 'odometer'}
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).verify_filter_hash()

    def test_first_time_incremental_short_circuits(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        # No prior metadata seeded.
        assert bundle.is_incremental_with_prior is False

        ResourcePreparer(bundle=bundle).verify_filter_hash()

    def test_matching_hash_passes(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        # The ``filters`` discriminated-union default is a fresh
        # ``VehiclesFilters()``, whose hash is the empty-object digest.
        matching_hash: str = hash_filter_model(VehiclesFilters())
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_RECORD_UTC,
            filters_hash=matching_hash,
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )
        assert bundle.is_incremental_with_prior is True

        # No raise.
        ResourcePreparer(bundle=bundle).verify_filter_hash()

    def test_mismatched_hash_raises(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_RECORD_UTC,
            filters_hash='f' * 64,  # never matches a real filter dump
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        with pytest.raises(FilterHashMismatchError):
            ResourcePreparer(bundle=bundle).verify_filter_hash()

    def test_internal_invariant_violation_when_metadata_disappears(
        self,
        tmp_path: Path,
    ) -> None:
        # Reproduce the contradictory state:
        # ``bundle.is_incremental_with_prior`` is True (the build phase
        # read non-None metadata) but the storage handler's metadata
        # cache subsequently reports None (the file was modified
        # between phases or the cache was tampered with).
        #
        # The user cannot recover from this — the message is framed
        # as a pyholman-internal invariant violation pointing at the
        # issue tracker, not as a user error suggesting a filesystem
        # action. Pin every key piece of the message so the framing
        # cannot silently regress to user-facing language.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        # Build a contradictory state: flag the bundle as having prior
        # metadata, but no metadata exists on disk so the storage
        # handler's cached read returns None. Mutating the bundle
        # field rather than seeding-and-deleting the sidecar avoids a
        # race with the handler's cache and pins exactly which
        # invariant is being violated.
        bundle.is_incremental_with_prior = True

        with pytest.raises(RuntimeError) as caught:
            ResourcePreparer(bundle=bundle).verify_filter_hash()

        message: str = str(caught.value)
        assert 'Internal invariant violation' in message
        assert "'vehicles'" in message
        assert str(bundle.storage_handler.metadata_path) in message
        # File-an-issue framing — the user's recovery is to report,
        # not to manipulate the working directory.
        assert 'file an issue' in message
        assert 'github.com/andrewjordan3/pyholman/issues' in message


# =============================================================================
# resolve_window
# =============================================================================


class TestResolveWindow:
    def test_snapshot_short_circuits(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path, resource_payload={'name': 'odometer'}
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()
        assert bundle.window_start is None

    def test_first_time_incremental_keeps_floor(self, tmp_path: Path) -> None:
        # First-time incremental: no prior metadata, no movement of
        # ``window_start`` away from the (None) floor.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)
        assert bundle.window_start is None

        ResourcePreparer(bundle=bundle).resolve_window()
        assert bundle.window_start is None

    def test_incremental_with_prior_uses_lookback_when_no_floor(
        self,
        tmp_path: Path,
    ) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            lookback_days=7,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_RECORD_UTC,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _PRIOR_RECORD_UTC - timedelta(days=7)


# =============================================================================
# build_query
# =============================================================================


class TestBuildQuery:
    def test_snapshot_passes_filters_through(self, tmp_path: Path) -> None:
        config: UserConfig = _build_user_config(
            tmp_path, resource_payload={'name': 'odometer'}
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).build_query()

        # Snapshot resources still get a query — just one whose filter
        # values come from the user config unchanged.
        assert bundle.query is not None

    def test_incremental_with_window_applies_with_window_start(
        self,
        tmp_path: Path,
    ) -> None:
        config: UserConfig = _build_user_config(
            tmp_path,
            lookback_days=7,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_RECORD_UTC,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window().build_query()

        assert bundle.query is not None
        assert isinstance(bundle.query, VehiclesQuery)
        # The query carries the windowed filter — its ``last_change_date``
        # equals the resolved window_start.
        assert bundle.query.last_change_date == bundle.window_start


# =============================================================================
# Configured-filter participation in window resolution
# =============================================================================
#
# The user-configured ``filters.last_change_date`` participates in
# ``window_start`` resolution alongside ``incremental.earliest_date``
# and (on steady-state runs) the prior watermark minus
# ``lookback_days``. The more recent of the cursor candidates wins,
# then the result is clamped up to ``earliest_date`` if that floor is
# set. The seven cases below mirror the worked-examples table from
# the bug report one-for-one; running the full
# ``apply_window_floor`` → ``resolve_window`` chain pins the resolved
# value, and earlier tests in this file pin the no-filter cases that
# this fix must leave untouched.


_FILTER_CURSOR_BOOTSTRAP: datetime = datetime(2026, 4, 1, tzinfo=UTC)
_FLOOR_DATE: date = date(2026, 4, 25)
_FLOOR_AS_DATETIME: datetime = datetime(2026, 4, 25, tzinfo=UTC)
_PRIOR_FOR_WATERMARK_WINS: datetime = datetime(2026, 4, 25, tzinfo=UTC) + timedelta(days=7)
# So that ``prior - lookback_days(=7)`` lands on 2026-04-25.
_FILTER_OLDER_THAN_WATERMARK: datetime = datetime(2026, 4, 24, tzinfo=UTC)
_FILTER_NEWER_THAN_WATERMARK: datetime = datetime(2026, 4, 26, tzinfo=UTC)
_HIGH_FLOOR: date = date(2026, 4, 27)
_HIGH_FLOOR_AS_DATETIME: datetime = datetime(2026, 4, 27, tzinfo=UTC)


def _resource_payload_with_filter_cursor(
    last_change_date: datetime,
) -> dict[str, Any]:
    return {
        'name': 'vehicles',
        'incremental': True,
        'filters': {'last_change_date': last_change_date.isoformat()},
    }


class TestConfiguredFilterParticipation:
    def test_bootstrap_filter_only(self, tmp_path: Path) -> None:
        # Scenario 1: Bootstrap, configured filter only. No floor, no
        # prior — the candidate is the configured cursor and nothing
        # raises it.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload=_resource_payload_with_filter_cursor(
                _FILTER_CURSOR_BOOTSTRAP,
            ),
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FILTER_CURSOR_BOOTSTRAP

    def test_bootstrap_filter_clamped_by_floor(self, tmp_path: Path) -> None:
        # Scenario 2: Bootstrap, configured filter is older than the
        # floor — the floor wins.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_FLOOR_DATE,
            resource_payload=_resource_payload_with_filter_cursor(
                _FILTER_CURSOR_BOOTSTRAP,
            ),
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FLOOR_AS_DATETIME

    def test_bootstrap_no_filter_keeps_existing_behavior(
        self,
        tmp_path: Path,
    ) -> None:
        # Scenario 3: Bootstrap, no configured filter, no floor.
        # ``window_start`` stays ``None`` — the existing behavior the
        # fix must not disturb.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start is None

    def test_steady_state_watermark_wins_over_older_filter(
        self,
        tmp_path: Path,
    ) -> None:
        # Scenario 4: Steady-state. Configured filter is older than
        # the lookback anchor, so the lookback anchor wins. This pins
        # that the existing watermark behavior is preserved when the
        # configured filter is older.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload=_resource_payload_with_filter_cursor(
                _FILTER_OLDER_THAN_WATERMARK,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_FOR_WATERMARK_WINS,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=_FILTER_OLDER_THAN_WATERMARK),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        expected_lookback_anchor: datetime = (
            _PRIOR_FOR_WATERMARK_WINS - timedelta(days=7)
        )
        assert bundle.window_start == expected_lookback_anchor

    def test_steady_state_filter_wins_over_older_watermark(
        self,
        tmp_path: Path,
    ) -> None:
        # Scenario 5: Steady-state. Configured filter is more recent
        # than the lookback anchor — the user is intentionally
        # advancing the cursor. The configured filter wins.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload=_resource_payload_with_filter_cursor(
                _FILTER_NEWER_THAN_WATERMARK,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_FOR_WATERMARK_WINS,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=_FILTER_NEWER_THAN_WATERMARK),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FILTER_NEWER_THAN_WATERMARK

    def test_steady_state_floor_clamps_both(self, tmp_path: Path) -> None:
        # Scenario 6: Steady-state. Floor is more recent than both
        # configured filter and lookback anchor — the floor clamps
        # both and wins.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_HIGH_FLOOR,
            resource_payload=_resource_payload_with_filter_cursor(
                _FILTER_OLDER_THAN_WATERMARK,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_FOR_WATERMARK_WINS,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=_FILTER_OLDER_THAN_WATERMARK),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _HIGH_FLOOR_AS_DATETIME

    def test_steady_state_no_filter_keeps_existing_behavior(
        self,
        tmp_path: Path,
    ) -> None:
        # Scenario 7: Steady-state, no configured filter. Falls back
        # to lookback-anchor-only — pins the existing behavior the
        # fix must not disturb.
        config: UserConfig = _build_user_config(
            tmp_path,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=_PRIOR_FOR_WATERMARK_WINS,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        expected_lookback_anchor: datetime = (
            _PRIOR_FOR_WATERMARK_WINS - timedelta(days=7)
        )
        assert bundle.window_start == expected_lookback_anchor

    # ------------------------------------------------------------------
    # earliest_date applies unconditionally (Items 1-9 below mirror the
    # remaining rows of the worked-examples table that the prior
    # 7-scenario block did not cover).
    # ------------------------------------------------------------------

    def test_bootstrap_earliest_date_only(self, tmp_path: Path) -> None:
        # Bootstrap with only ``earliest_date`` configured. The floor
        # alone produces the candidate window_start; this is the
        # scenario the user reported as a bug. With ``_clamp_floor``
        # in apply_window_floor, ``candidate=None, floor=set`` returns
        # the floor — so the bug was already addressed by the prior
        # filter-resolution work, and this test pins the behavior so
        # a future refactor cannot silently regress it.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_FLOOR_DATE,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FLOOR_AS_DATETIME

    def test_bootstrap_configured_filter_wins_over_older_floor(
        self,
        tmp_path: Path,
    ) -> None:
        # Bootstrap, filter is more recent than the floor — filter
        # wins. Mirrors the "configured filter wins" row of the
        # bootstrap section of the table.
        configured_filter_newer: datetime = datetime(2026, 4, 30, tzinfo=UTC)
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_FLOOR_DATE,
            resource_payload=_resource_payload_with_filter_cursor(
                configured_filter_newer,
            ),
        )
        bundle: ResourceBundle = _build_bundle(tmp_path, user_config=config)

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == configured_filter_newer

    def test_steady_state_earliest_date_only_above_anchor(
        self,
        tmp_path: Path,
    ) -> None:
        # Steady-state with only ``earliest_date`` set, floor more
        # recent than the lookback anchor. Floor wins.
        prior_record_utc: datetime = datetime(2026, 4, 27, tzinfo=UTC)
        # lookback_anchor lands on 2026-04-20 with lookback_days=7.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_FLOOR_DATE,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FLOOR_AS_DATETIME

    def test_steady_state_earliest_date_creates_large_gap(
        self,
        tmp_path: Path,
    ) -> None:
        # Same shape as above but with a much-older prior watermark,
        # so the gap between (prior_most_recent_record_utc) and
        # (resolved window_start) is large. Resolution behavior is
        # unchanged — the warning side of the test belongs to the
        # orchestrator-level assertions.
        prior_record_utc: datetime = datetime(2026, 3, 27, tzinfo=UTC)
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=_FLOOR_DATE,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == _FLOOR_AS_DATETIME

    def test_steady_state_earliest_date_inert_below_anchor(
        self,
        tmp_path: Path,
    ) -> None:
        # ``earliest_date`` lower than the lookback anchor — the floor
        # has no effect on the resolution and the lookback anchor
        # wins. The ``_clamp_floor`` in apply_window_floor leaves
        # window_start at the floor (lower of the two), and
        # ``resolve_window``'s ``max(current, anchor)`` then raises it
        # to the anchor.
        low_floor_date: date = date(2026, 3, 15)
        prior_record_utc: datetime = datetime(2026, 3, 27, tzinfo=UTC)
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=low_floor_date,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        expected_anchor: datetime = prior_record_utc - timedelta(days=7)
        assert bundle.window_start == expected_anchor

    def test_steady_state_earliest_date_inert_filter_wins(
        self,
        tmp_path: Path,
    ) -> None:
        # ``earliest_date`` is below the anchor; configured filter is
        # above the anchor. Filter wins; floor never participates.
        low_floor_date: date = date(2026, 3, 15)
        configured_filter: datetime = datetime(2026, 3, 25, tzinfo=UTC)
        prior_record_utc: datetime = datetime(2026, 3, 27, tzinfo=UTC)
        # lookback_anchor = 2026-03-20 — between floor and filter.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=low_floor_date,
            resource_payload=_resource_payload_with_filter_cursor(
                configured_filter,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=configured_filter),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == configured_filter

    def test_steady_state_all_three_set_earliest_date_wins(
        self,
        tmp_path: Path,
    ) -> None:
        # All three inputs set; ``earliest_date`` is the most recent.
        # Floor wins after the chained ``max(...)``.
        floor_date: date = date(2026, 4, 30)
        configured_filter: datetime = datetime(2026, 4, 26, tzinfo=UTC)
        prior_record_utc: datetime = datetime(2026, 5, 5, tzinfo=UTC)
        # lookback_anchor = 2026-04-28.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=floor_date,
            resource_payload=_resource_payload_with_filter_cursor(
                configured_filter,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=configured_filter),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == datetime(2026, 4, 30, tzinfo=UTC)

    def test_steady_state_filter_wins_floor_still_above_anchor(
        self,
        tmp_path: Path,
    ) -> None:
        # Configured filter wins resolution, but ``earliest_date`` is
        # still above the lookback anchor. The resolution result is
        # the filter (most recent); the gap is real and the warning
        # tested at the orchestrator level fires for this case even
        # though the floor isn't the resolution winner.
        floor_date: date = date(2026, 4, 25)
        configured_filter: datetime = datetime(2026, 4, 30, tzinfo=UTC)
        prior_record_utc: datetime = datetime(2026, 4, 27, tzinfo=UTC)
        # lookback_anchor = 2026-04-20; floor (4-25) is above it.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=floor_date,
            resource_payload=_resource_payload_with_filter_cursor(
                configured_filter,
            ),
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(
                VehiclesFilters(last_change_date=configured_filter),
            ),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == configured_filter

    def test_steady_state_earliest_date_equals_anchor(
        self,
        tmp_path: Path,
    ) -> None:
        # ``earliest_date`` equals the lookback anchor exactly. Strict
        # ``>`` comparison means no warning fires (tested separately
        # at the orchestrator level); resolution returns the value
        # they share.
        floor_date: date = date(2026, 4, 25)
        prior_record_utc: datetime = datetime(2026, 5, 2, tzinfo=UTC)
        # lookback_anchor = 2026-04-25 = floor. They tie.
        config: UserConfig = _build_user_config(
            tmp_path,
            earliest_date=floor_date,
            resource_payload={'name': 'vehicles', 'incremental': True},
        )
        seed_metadata: StorageMetadata = _metadata_for(
            most_recent=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        bundle: ResourceBundle = _build_bundle(
            tmp_path,
            user_config=config,
            seed_metadata=seed_metadata,
        )

        ResourcePreparer(bundle=bundle).resolve_window()

        assert bundle.window_start == datetime(2026, 4, 25, tzinfo=UTC)
