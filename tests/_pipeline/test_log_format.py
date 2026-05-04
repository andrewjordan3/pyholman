# tests/_pipeline/test_log_format.py
"""
Unit tests for :func:`format_window_resolution_gap_warning`.

The 16 scenarios mirror the worked-examples table from the bug report
1:1. Each row is encoded as a parametrized case so the warning's
trigger condition can be verified end-to-end on the same shape the
production resolution path produces. Resolution math itself is
exercised in :mod:`tests._pipeline.test_preparer`; this file pins the
pure-function warning emitted afterward.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from pyholman._pipeline import (
    WindowResolutionAudit,
    format_window_resolution_gap_warning,
)

__all__: list[str] = []


_LOOKBACK_DAYS: int = 7


@dataclass(frozen=True, slots=True)
class _Scenario:
    """One row of the worked-examples table.

    ``prior_watermark_lookback`` is the table's "prior_watermark -
    lookback" column rendered directly; the test computes
    ``prior_most_recent_record_utc`` by adding ``lookback_days`` back
    so the audit dataclass receives the same shape the orchestrator
    constructs from the storage handler.
    """

    label: str
    is_incremental_with_prior: bool
    earliest_date: date | None
    configured_filter_last_change_date: datetime | None
    prior_watermark_lookback: datetime | None
    expected_resolved_window_start: datetime | None
    expects_warning: bool


def _audit_for(scenario: _Scenario) -> WindowResolutionAudit:
    prior_most_recent_record_utc: datetime | None = (
        None
        if scenario.prior_watermark_lookback is None
        else scenario.prior_watermark_lookback + timedelta(days=_LOOKBACK_DAYS)
    )
    return WindowResolutionAudit(
        is_incremental_with_prior=scenario.is_incremental_with_prior,
        earliest_date=scenario.earliest_date,
        configured_filter_last_change_date=(
            scenario.configured_filter_last_change_date
        ),
        lookback_days=_LOOKBACK_DAYS,
        prior_most_recent_record_utc=prior_most_recent_record_utc,
        resolved_window_start=scenario.expected_resolved_window_start,
    )


# Every row of the prompt's table, encoded as a single source of truth.
# Datetimes are tz-aware UTC to match the production resolution path.
_SCENARIOS: list[_Scenario] = [
    _Scenario(
        label='bootstrap_earliest_date_only',
        is_incremental_with_prior=False,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=None,
        prior_watermark_lookback=None,
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='bootstrap_configured_filter_only',
        is_incremental_with_prior=False,
        earliest_date=None,
        configured_filter_last_change_date=datetime(2026, 4, 1, tzinfo=UTC),
        prior_watermark_lookback=None,
        expected_resolved_window_start=datetime(2026, 4, 1, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='bootstrap_filter_clamped_by_floor',
        is_incremental_with_prior=False,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=datetime(2026, 4, 1, tzinfo=UTC),
        prior_watermark_lookback=None,
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='bootstrap_configured_filter_wins',
        is_incremental_with_prior=False,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=datetime(2026, 4, 30, tzinfo=UTC),
        prior_watermark_lookback=None,
        expected_resolved_window_start=datetime(2026, 4, 30, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='bootstrap_no_inputs',
        is_incremental_with_prior=False,
        earliest_date=None,
        configured_filter_last_change_date=None,
        prior_watermark_lookback=None,
        expected_resolved_window_start=None,
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_watermark_wins',
        is_incremental_with_prior=True,
        earliest_date=None,
        configured_filter_last_change_date=datetime(2026, 4, 24, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 4, 25, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_configured_filter_wins',
        is_incremental_with_prior=True,
        earliest_date=None,
        configured_filter_last_change_date=datetime(2026, 4, 26, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 4, 25, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 26, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_both_clamped_by_floor',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 27),
        configured_filter_last_change_date=datetime(2026, 4, 24, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 4, 25, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 27, tzinfo=UTC),
        expects_warning=True,
    ),
    _Scenario(
        label='steady_state_no_configured_filter',
        is_incremental_with_prior=True,
        earliest_date=None,
        configured_filter_last_change_date=None,
        prior_watermark_lookback=datetime(2026, 4, 25, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_earliest_date_only',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=None,
        prior_watermark_lookback=datetime(2026, 4, 20, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=True,
    ),
    _Scenario(
        label='steady_state_earliest_date_creates_large_gap',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=None,
        prior_watermark_lookback=datetime(2026, 3, 20, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=True,
    ),
    _Scenario(
        label='steady_state_earliest_date_inert',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 3, 15),
        configured_filter_last_change_date=None,
        prior_watermark_lookback=datetime(2026, 3, 20, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 3, 20, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_earliest_date_inert_filter_wins',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 3, 15),
        configured_filter_last_change_date=datetime(2026, 3, 25, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 3, 20, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 3, 25, tzinfo=UTC),
        expects_warning=False,
    ),
    _Scenario(
        label='steady_state_all_three_earliest_date_wins',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 30),
        configured_filter_last_change_date=datetime(2026, 4, 26, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 4, 28, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 30, tzinfo=UTC),
        expects_warning=True,
    ),
    _Scenario(
        label='steady_state_filter_wins_earliest_date_still_forces_gap',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=datetime(2026, 4, 30, tzinfo=UTC),
        prior_watermark_lookback=datetime(2026, 4, 20, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 30, tzinfo=UTC),
        expects_warning=True,
    ),
    _Scenario(
        label='steady_state_earliest_date_equals_anchor',
        is_incremental_with_prior=True,
        earliest_date=date(2026, 4, 25),
        configured_filter_last_change_date=None,
        prior_watermark_lookback=datetime(2026, 4, 25, tzinfo=UTC),
        expected_resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        expects_warning=False,
    ),
]


@pytest.mark.parametrize(
    'scenario',
    _SCENARIOS,
    ids=[scenario.label for scenario in _SCENARIOS],
)
def test_warning_trigger_matches_table(scenario: _Scenario) -> None:
    audit: WindowResolutionAudit = _audit_for(scenario)
    rendered: str | None = format_window_resolution_gap_warning(
        audit, resource_name='vehicles',
    )
    if scenario.expects_warning:
        assert rendered is not None, (
            f"scenario {scenario.label!r} expected a warning but the "
            f'helper returned None'
        )
    else:
        assert rendered is None, (
            f"scenario {scenario.label!r} expected no warning but the "
            f'helper returned: {rendered!r}'
        )


class TestWarningMessageShape:
    """Pin the substance of the rendered message for one canonical
    truncation case (the ``earliest_date_creates_large_gap`` row)."""

    def test_message_names_resource_floor_anchor_resolved_and_gap_bounds(
        self,
    ) -> None:
        prior_most_recent: datetime = datetime(2026, 3, 27, tzinfo=UTC)
        audit: WindowResolutionAudit = WindowResolutionAudit(
            is_incremental_with_prior=True,
            earliest_date=date(2026, 4, 25),
            configured_filter_last_change_date=None,
            lookback_days=_LOOKBACK_DAYS,
            prior_most_recent_record_utc=prior_most_recent,
            resolved_window_start=datetime(2026, 4, 25, tzinfo=UTC),
        )

        rendered: str | None = format_window_resolution_gap_warning(
            audit, resource_name='maintenance_purchase_orders',
        )

        assert rendered is not None
        # Resource name surfaces verbatim.
        assert "'maintenance_purchase_orders'" in rendered
        # The floor and the watermark window bounds appear as
        # ISO-8601 strings.
        assert '2026-04-25T00:00:00+00:00' in rendered  # floor / resolved
        expected_anchor: datetime = prior_most_recent - timedelta(days=_LOOKBACK_DAYS)
        assert expected_anchor.isoformat() in rendered
        # The gap bounds — between the latest record on disk and the
        # resolved window_start — are concretely named.
        assert prior_most_recent.isoformat() in rendered
        # The recovery is mentioned.
        assert 'remove or lower earliest_date' in rendered
        # And the "intentional truncation is fine" branch is named so
        # a user who set the floor deliberately knows they can ignore.
        assert 'intentional' in rendered
