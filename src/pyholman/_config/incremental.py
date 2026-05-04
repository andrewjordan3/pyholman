# src/pyholman/_config/incremental.py
"""Incremental-update section of the user configuration."""

from datetime import date

from pydantic import Field

from pyholman._core import FrozenModel

__all__: list[str] = ['IncrementalConfig']


class IncrementalConfig(FrozenModel):
    """
    Settings for endpoints pulled with delta queries.

    These values drive the orchestration layer that composes the HTTP
    client with on-disk storage — this model only captures the policy.
    One-shot full-refresh runs do not read these fields.

    Attributes:
        lookback_days: How far back (in days) each incremental pull
            reaches to catch late-arriving or corrected records. The
            refresh window anchors to the most recent record already on
            disk, not to today's date, so a missed cron still catches
            every record in the window on the next successful run.
            Defaults to ``7`` — the right knob for most weekly cadences.
            Set to ``1`` for nightly cron jobs that don't need a longer
            late-arrival window; set higher only when a known correction
            pipeline takes longer than a week to settle.
        earliest_date: Project-level hard floor for the refresh
            window. Applies unconditionally to every incremental
            resource on every run, whether or not a per-resource
            ``filters.last_change_date`` is set. Participates in
            window resolution alongside the prior watermark
            (``most_recent_record_utc - lookback_days``) and the
            per-resource cursor; the most recent of those candidates
            wins, and the floor clamps the result up if it sits
            above the winner. On a bootstrap run with no other
            inputs, ``earliest_date`` alone drives the window. On a
            steady-state run, when the floor is more recent than the
            prior-watermark window, pyholman logs a WARNING
            describing the resulting data gap and the recovery
            (remove or lower the floor); the run still proceeds
            because the floor is treated as the user's stated intent.
            Useful when Holman's retention policy makes older queries
            return nothing, or when bounding a backfill. ``None``
            disables the floor. A ``datetime.date`` rather than a
            full datetime because a floor is naturally date-valued;
            the orchestration layer promotes it to a UTC datetime
            when building a query.
    """

    lookback_days: int = Field(default=7, ge=1)
    earliest_date: date | None = None
