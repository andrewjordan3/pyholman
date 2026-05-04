# src/pyholman/_pipeline/log_format.py
"""
Per-resource observability log-line formatting.

Three helpers used by the orchestrator's per-resource processing loop:

    - :func:`format_configured_filters` — render the user's YAML filter
      config for a resource, so a reader can see exactly what was
      asked for.
    - :func:`format_window_resolution_audit` — render every input that
      contributes to incremental ``window_start`` resolution (the
      project-level floor, the prior watermark, the lookback config,
      the derived lookback anchor) alongside the resolved value, so a
      reader can tell which input drove the result.
    - :func:`format_resolved_query_parameters` — render the resolved
      query input the transport will send, so a reader can see what
      actually parameterizes the HTTP request after the orchestrator
      has applied incremental-window resolution, lookback, and any
      other transformations.

Together the three lines answer the question "did my filter make it
onto the wire, and which input determined the resolved window?"
without requiring a trip into the source code. The formatting is pure
string construction — no I/O, no logging — so the orchestrator owns
the call and the log level decision.
"""

from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from pyholman._core import FrozenModel, QueryInputBase, ResponseModel

__all__: list[str] = [
    'WindowResolutionAudit',
    'format_configured_filters',
    'format_resolved_query_parameters',
    'format_window_resolution_audit',
    'format_window_resolution_gap_warning',
]


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowResolutionAudit:
    """
    Bundle of every input that contributes to ``window_start`` resolution
    plus the resolved value, sized to be passed verbatim into
    :func:`format_window_resolution_audit`.

    Exists because the formatter naturally needs six related values —
    enough to trip ruff's ``PLR0913`` when expressed as kwargs and
    enough that "they always travel together" justifies a dataclass
    per CLAUDE.md's parameter-bundling rule. Frozen so a caller cannot
    mutate the snapshot of one resource's resolution while a log line
    is being formatted.
    """

    is_incremental_with_prior: bool
    earliest_date: date | None
    configured_filter_last_change_date: datetime | None
    lookback_days: int
    prior_most_recent_record_utc: datetime | None
    resolved_window_start: datetime | None

# Marker the configured-filters formatter emits when the user supplied
# no filter overrides. Pinned to a module constant so test assertions
# and the production rendering stay in lockstep.
_NO_FILTERS_MARKER: str = 'none'

# Marker the window-resolution-audit formatter emits for inputs that
# don't apply on this code path (e.g., ``prior_most_recent_record_utc``
# on a bootstrap run that has no prior metadata to read). Distinct
# from ``None`` so a reader can tell "this input doesn't exist for
# this run" apart from "this input is configured but unset."
_NOT_APPLICABLE_MARKER: str = 'n/a'


def format_configured_filters(filter_model: FrozenModel | None) -> str:
    """
    Render the user's configured filter values as ``key=value`` pairs.

    Only fields the user actually set are rendered — defaulted-to-None
    fields are omitted via ``model_dump(exclude_none=True)``. The intent
    is "what did the user type?", not "what does the filter schema
    declare?". A model with no user-set fields, and ``filter_model is
    None`` itself, both render as :data:`_NO_FILTERS_MARKER` so a log
    reader sees one consistent shape for the empty case.

    Datetime values are rendered via :meth:`datetime.isoformat`.
    Sequences are rendered as lists for stability across endpoints
    whose filter schemas use either ``tuple`` or ``list``. Other
    values fall through to :func:`repr` so strings show their quotes
    and ints / floats show their numeric form unambiguously.

    Args:
        filter_model: A validated filter model from
            :attr:`ResourceConfig.filters`, or ``None`` if no filter
            block is configured (e.g., the ``fetch`` programmatic
            entry point).

    Returns:
        ``"key=value key=value ..."`` joined by single spaces, or
        :data:`_NO_FILTERS_MARKER` when no fields were set.
    """
    if filter_model is None:
        return _NO_FILTERS_MARKER

    user_set_fields: dict[str, Any] = filter_model.model_dump(exclude_none=True)
    if not user_set_fields:
        return _NO_FILTERS_MARKER

    return ' '.join(
        f'{name}={_format_value(value)}' for name, value in user_set_fields.items()
    )


def format_resolved_query_parameters(query: QueryInputBase[ResponseModel]) -> str:
    """
    Render the wire-bound query parameters as ``key=value`` pairs.

    Walks the query dataclass's fields and renders only those that
    carry an ``api_key`` entry in their metadata — i.e., fields that
    will appear on the URL. Structural fields like ``base_url`` (which
    has no ``api_key`` metadata) are deliberately excluded. ``None``
    values are rendered explicitly as ``None`` so a reader sees
    "this parameter is unset" as a distinct outcome from "this
    parameter wasn't logged."

    The rendering uses Python attribute names (snake_case) rather than
    Holman's wire names (camelCase, accessible via the ``api_key``
    metadata) so the line matches what a user reads in
    ``user_config.yaml`` and in the response-model and filter docs.

    Args:
        query: The fully built query input the transport will send.

    Returns:
        ``"key=value key=value ..."`` joined by single spaces.
    """
    rendered_pairs: list[str] = []
    for field_definition in fields(query):
        if field_definition.metadata.get('api_key') is None:
            continue
        field_value: Any = getattr(query, field_definition.name)
        rendered_pairs.append(f'{field_definition.name}={_format_value(field_value)}')
    return ' '.join(rendered_pairs)


def format_window_resolution_audit(audit: WindowResolutionAudit) -> str:
    """
    Render the inputs and the resolved value of incremental window resolution.

    The orchestrator's ``window_start`` for an incremental resource is
    the maximum of (the configured filter cursor, the
    ``prior_most_recent_record_utc - lookback_days`` lookback anchor),
    clamped up to the project-level ``earliest_date`` floor. The
    lookback anchor applies only on incremental-with-prior runs; the
    configured filter and the floor apply on every incremental run.
    The formatter shows every input that participates plus the
    resolved value, so a reader can correlate inputs to output and
    recognize which input won — without needing to know the
    resolution math.

    On a bootstrap run (``is_incremental_with_prior`` is ``False``)
    there is no prior watermark and no derived lookback anchor; both
    render as :data:`_NOT_APPLICABLE_MARKER` so a reader sees the
    inputs exist as concepts but didn't apply on this run. The
    configured ``lookback_days`` always renders as its concrete value
    because it is a config setting that exists on every run, even
    when its effect is gated.

    The derived ``lookback_anchor`` is recomputed inside the formatter
    using the same formula
    (``prior_most_recent_record_utc - timedelta(days=lookback_days)``)
    that :meth:`ResourcePreparer.resolve_window` uses. The duplication
    is deliberate: showing the anchor in the log next to the resolved
    value lets a reader verify the resolution math without re-running
    it themselves. If the resolution formula ever changes, this
    formatter must change in lockstep — the test suite pins the
    expected values so silent drift fails loudly.

    Args:
        audit: A :class:`WindowResolutionAudit` snapshot of every
            input plus the resolved value, captured in the
            orchestrator's per-resource processing loop.

    Returns:
        ``"key=value key=value ..."`` joined by single spaces.
    """
    rendered_lookback_anchor: str
    if audit.prior_most_recent_record_utc is None:
        rendered_prior_watermark: str = _NOT_APPLICABLE_MARKER
        rendered_lookback_anchor = _NOT_APPLICABLE_MARKER
    else:
        rendered_prior_watermark = audit.prior_most_recent_record_utc.isoformat()
        lookback_anchor: datetime = audit.prior_most_recent_record_utc - timedelta(
            days=audit.lookback_days
        )
        rendered_lookback_anchor = lookback_anchor.isoformat()

    rendered_earliest_date: str = (
        _format_value(None)
        if audit.earliest_date is None
        else audit.earliest_date.isoformat()
    )

    return ' '.join(
        [
            f'is_incremental_with_prior={audit.is_incremental_with_prior}',
            f'earliest_date={rendered_earliest_date}',
            f'configured_filter_last_change_date='
            f'{_format_value(audit.configured_filter_last_change_date)}',
            f'lookback_days={audit.lookback_days}',
            f'prior_most_recent_record_utc={rendered_prior_watermark}',
            f'lookback_anchor={rendered_lookback_anchor}',
            f'resolved_window_start={_format_value(audit.resolved_window_start)}',
        ]
    )


def format_window_resolution_gap_warning(
    audit: WindowResolutionAudit,
    *,
    resource_name: str,
) -> str | None:
    """
    Render a WARNING message when ``earliest_date`` forces a data gap.

    A "data gap" exists when the orchestrator is doing a steady-state
    incremental run (prior metadata exists) and ``earliest_date`` is
    strictly more recent than the lookback anchor — meaning the new
    pull starts after the latest record on disk and records updated
    between those two points will not be fetched. The user may have
    set the floor deliberately (truncating older history) or
    accidentally (forgot it was set, picked the wrong year), and the
    warning surfaces both possibilities so they can confirm or
    correct.

    The trigger does **not** depend on whether ``configured_filter_
    last_change_date`` is set or which input wins the resolution
    ``max(...)``. Even when the configured filter pushes the resolved
    window above ``earliest_date`` and the floor is technically
    inert as the resolution winner, the floor's mere presence above
    the watermark means a user who removed it would still hit the
    same gap (because the filter would still win) — so the warning
    accurately describes the state of affairs from the watermark's
    point of view.

    Returns:
        ``None`` when no warning is warranted (bootstrap, no
        ``earliest_date``, or floor at or below the watermark
        anchor). A formatted message string otherwise.
    """
    if not audit.is_incremental_with_prior:
        return None
    if audit.earliest_date is None:
        return None
    if audit.prior_most_recent_record_utc is None:
        # Defensive: ``is_incremental_with_prior`` is meant to imply
        # a prior watermark. If the audit reports the contradictory
        # state, the orchestrator's invariant guard upstream will
        # already have raised; here we just refuse to warn rather
        # than crash on the missing input.
        return None

    earliest_date_utc: datetime = datetime.combine(
        audit.earliest_date, time.min, tzinfo=UTC,
    )
    lookback_anchor: datetime = audit.prior_most_recent_record_utc - timedelta(
        days=audit.lookback_days,
    )
    if earliest_date_utc <= lookback_anchor:
        return None

    # The resolution path always produces a non-None value when
    # ``earliest_date`` is set on an incremental-with-prior run
    # (resolved_window_start ≥ earliest_date_utc), so dereferencing
    # here is safe. The assertion narrows the type for the f-string
    # without burying the invariant in a runtime branch.
    assert audit.resolved_window_start is not None, (
        'resolved_window_start cannot be None when earliest_date is set'
    )

    return (
        f'Resource {resource_name!r}: earliest_date floor '
        f'({earliest_date_utc.isoformat()}) is more recent than the '
        f'incremental watermark window '
        f'({lookback_anchor.isoformat()}). The resolved window_start of '
        f'{audit.resolved_window_start.isoformat()} will create a gap in '
        f'the dataset between {audit.prior_most_recent_record_utc.isoformat()} '
        f'and {audit.resolved_window_start.isoformat()}. If this is '
        f'intentional (e.g., you are deliberately truncating older data), '
        f'no action is needed. If it is not, remove or lower earliest_date '
        f'in your configuration before the next run.'
    )


def _format_value(value: Any) -> str:
    """
    Render a single field value to its log-line form.

    Order matters: ``datetime`` is checked before the sequence branch
    because ``datetime`` is not a sequence but the fallback
    :func:`repr` would still work — keeping the explicit branch for
    clarity. Sequences are normalized to ``list`` so a ``tuple`` like
    ``lessee_codes`` and a ``list`` from a future filter schema
    render identically.
    """
    if value is None:
        return 'None'
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return repr(list(value))
    return repr(value)
