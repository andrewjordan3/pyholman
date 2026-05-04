# src/pyholman/orchestrator.py
"""
Top-level entry point for config-driven pyholman runs.

:class:`Orchestrator` is the public, user-facing class that ties the
pipeline pieces together. Construction loads and validates the YAML
config and installs pyholman's logging policy; :meth:`run` iterates
``user_config.resources`` in declaration order through three phases:

    1. Build — :class:`ResourceBundleBuilder` per resource. No network
       I/O beyond a metadata-sidecar read per resource.
    2. Prepare — :class:`ResourcePreparer` per bundle. Hash check,
       window resolution, query construction. Still no network.
    3. Process — :class:`ResourceProcessor` per bundle, inside one
       :class:`HolmanClient` context. API calls and persists.

Per-resource fail-fast: a failure on resource N stops iteration with
resources N+1..end unprocessed; bundles that completed ``persist``
before the failure are on disk and survive.
"""

import logging
from pathlib import Path

from pyholman._client import HolmanClient
from pyholman._clock import Clock, Stopwatch, SystemClock
from pyholman._config import UserConfig
from pyholman._logger import setup_logger
from pyholman._pipeline import (
    ResourceBundle,
    ResourceBundleBuilder,
    ResourcePreparer,
    ResourceProcessor,
    WindowResolutionAudit,
    format_configured_filters,
    format_resolved_query_parameters,
    format_window_resolution_audit,
    format_window_resolution_gap_warning,
)
from pyholman._storage import StorageMetadata

__all__: list[str] = ['Orchestrator']

logger: logging.Logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Top-level entry point for config-driven pyholman runs.

    Construction loads and validates the YAML at ``config_path``,
    configures pyholman's logger from the validated config, and
    captures a :class:`SystemClock`. No network or per-resource I/O
    happens at construction time.

    :meth:`run` executes the configured resources in declaration order
    via three phases (build, prepare, process). Per-resource
    fail-fast: an exception on resource N stops the run with
    resources N+1..end unprocessed; bundles that completed ``persist``
    before the failure are on disk and survive.

    Args:
        config_path: Path to the YAML configuration file. Accepts a
            ``str`` or :class:`~pathlib.Path`; strings are converted
            to ``Path`` at the boundary so internal state stays
            ``Path``-typed. ``UserConfig.from_yaml`` is called
            immediately; if it raises, the failure surfaces unchanged
            through whatever stdlib logging policy is in effect
            (pyholman's policy isn't installed until after the YAML
            loads cleanly).

    Raises:
        FileNotFoundError: If ``config_path`` does not exist.
        RuntimeError: If ``HOLMAN_CLIENT_SECRET`` is unset or empty
            at load time, or if the YAML supplies the secret directly
            (it must come from the environment).
        pydantic.ValidationError: If the YAML content fails any field
            or model validator.
    """

    __slots__ = ('_clock', '_config_path', '_user_config')

    def __init__(self, config_path: str | Path) -> None:
        resolved_path: Path = Path(config_path)
        self._config_path: Path = resolved_path
        self._user_config: UserConfig = UserConfig.from_yaml(resolved_path)
        setup_logger(self._user_config.logger)
        self._clock: Clock = SystemClock()

        logger.info('Loaded config from %s', resolved_path)
        logger.debug(
            'Validated configuration with %d resources',
            len(self._user_config.resources),
        )

    def run(self) -> None:
        """
        Execute the configured resources in declaration order.

        Three phases:
            1. Build — one :class:`ResourceBundle` per
               ``user_config.resources`` entry. Reads the metadata
               sidecar (if any) per resource via the cached storage
               handler; does not open an HTTP client.
            2. Prepare — verify filter hash, resolve incremental
               window, build query. Still no network I/O. Hash
               mismatches raise here, before any HTTP request.
            3. Process — iterate bundles inside one
               :class:`HolmanClient` context, running the processor
               chain (execute, materialize, merge, persist) per
               bundle. The orchestrator stamps each bundle's
               ``started_at_utc`` and starts a per-resource
               :class:`Stopwatch` at this point — not at build time —
               so the metadata's ``run_started_utc`` and the
               per-resource elapsed log line both reflect the
               resource's actual processing window rather than the
               wall-clock instant the bundle was constructed. Per
               resource the loop also emits the user-configured
               filters at INFO, the window-resolution audit (every
               input that contributes to ``window_start`` plus the
               resolved value, for incremental resources) at INFO,
               and the resolved wire-bound query parameters at DEBUG
               so a reader can confirm whether a configured filter
               survived window resolution and which input drove the
               resolved value.

        Per-resource fail-fast: if processing resource N raises,
        resources N+1..end are not attempted. The exception
        propagates unchanged so callers can catch
        :class:`FilterHashMismatchError`, :class:`HolmanError`, etc.
        specifically. Bundles that completed ``persist`` before the
        failure are on disk and survive.

        Side Effects:
            Reads each configured resource's metadata sidecar (if
            any). Issues OAuth token requests and per-resource API
            calls. Writes data files and metadata sidecars under
            ``user_config.working_directory``.

        Raises:
            FilterHashMismatchError: From the prepare phase when a
                resource's stamped filter hash differs from its
                current configuration's hash.
            HolmanError, TransientHolmanError, RateLimitError:
                Propagated from the transport unchanged.
            ValueError: Propagated from the storage handler when a
                resource's collected records are empty (the
                locked-design failure mode).
        """
        run_stopwatch: Stopwatch = Stopwatch.start(clock=self._clock)
        resource_count: int = len(self._user_config.resources)

        logger.info('Starting run with %d resources', resource_count)

        bundles: list[ResourceBundle] = self._build_resource_bundles()
        self._prepare_resource_bundles(bundles)
        with HolmanClient(self._user_config) as client:
            self._process_resource_bundles(bundles, client)

        run_elapsed_seconds: float = run_stopwatch.elapsed_seconds(clock=self._clock)
        logger.info(
            'Completed all %d resources (run elapsed: %.2fs)',
            resource_count,
            run_elapsed_seconds,
        )

    def _build_resource_bundles(self) -> list[ResourceBundle]:
        """Iterate ``user_config.resources`` and run the builder chain per entry."""
        bundles: list[ResourceBundle] = []
        for resource_config in self._user_config.resources:
            bundle: ResourceBundle = (
                ResourceBundleBuilder(
                    resource_config=resource_config,
                    user_config=self._user_config,
                    clock=self._clock,
                )
                .lookup_registry_entry()
                .construct_storage_handler()
                .compute_incremental_flags()
                .apply_window_floor()
                .build()
            )
            bundles.append(bundle)
        return bundles

    @staticmethod
    def _prepare_resource_bundles(bundles: list[ResourceBundle]) -> None:
        """Iterate bundles and run the preparer chain on each."""
        for bundle in bundles:
            (
                ResourcePreparer(bundle=bundle)
                .verify_filter_hash()
                .resolve_window()
                .build_query()
            )

    def _process_resource_bundles(
        self,
        bundles: list[ResourceBundle],
        client: HolmanClient,
    ) -> None:
        """
        Iterate bundles and run the processor chain on each.

        For each bundle the orchestrator stamps ``bundle.started_at_utc``
        and starts a fresh per-resource :class:`Stopwatch` immediately
        before the processor chain runs. Doing both here — rather than
        at builder time — means the metadata's ``run_started_utc`` and
        the per-resource elapsed log line both measure the resource's
        actual processing window and not whatever wall-clock instant
        the bundle happened to be constructed at.

        Per-resource fail-fast: an exception in resource N's chain
        stops iteration. Resources before N have completed ``persist``
        already; resources after N are not attempted. The orchestrator
        emits an ERROR log naming the failing resource (with
        ``exc_info=True`` so the traceback lands in the file logs),
        then re-raises the original exception unchanged.
        """
        for bundle in bundles:
            logger.info('Starting resource %s', bundle.resource_name)

            # First-time-incremental ("bootstrap") runs are operationally
            # different from steady-state incremental runs — there's
            # nothing to merge against, so the resource pulls a full
            # snapshot. Without this line the run log gives no signal
            # that this is happening; it looks identical to a normal
            # incremental run until the user notices the metadata
            # sidecar is fresh.
            if bundle.is_incremental and not bundle.is_incremental_with_prior:
                logger.info(
                    "Resource %r: no existing metadata found; performing "
                    'bootstrap load for incremental resource.',
                    bundle.resource_name,
                )

            # Pair: configured filters (INFO, what the user asked for)
            # and resolved query parameters (DEBUG, what actually
            # parameterizes the wire request after window resolution
            # and lookback). Together a reader can answer "did my
            # filter make it onto the wire, and what did the final
            # query look like?" without reading source. The query was
            # built in the prepare phase, so ``bundle.query`` is
            # already populated when this loop runs.
            logger.info(
                'Resource %r configured filters: %s',
                bundle.resource_name,
                format_configured_filters(bundle.resource_config.filters),
            )

            # Window-resolution audit: surface every input that
            # contributes to ``window_start`` so a user reading the log
            # can recognize which one drove the resolved value.
            # Snapshot resources have no window resolution to audit —
            # ``window_start`` stays ``None`` regardless of inputs — so
            # the line is gated on ``is_incremental``. The cached
            # metadata read here is free; the storage handler memoized
            # it during the build phase.
            if bundle.is_incremental:
                prior_metadata: StorageMetadata | None = (
                    bundle.storage_handler.read_metadata()
                )
                prior_most_recent_record_utc = (
                    prior_metadata.most_recent_record_utc
                    if prior_metadata is not None
                    else None
                )
                # ``getattr`` keeps the access robust to a future
                # filter class that does not inherit
                # :class:`IncrementalFilters` — every incremental
                # filter currently does, but the orchestrator should
                # not crash if a registry change drifts.
                configured_filter_last_change_date = getattr(
                    bundle.resource_config.filters,
                    'last_change_date',
                    None,
                )
                audit: WindowResolutionAudit = WindowResolutionAudit(
                    is_incremental_with_prior=bundle.is_incremental_with_prior,
                    earliest_date=self._user_config.incremental.earliest_date,
                    configured_filter_last_change_date=(
                        configured_filter_last_change_date
                    ),
                    lookback_days=self._user_config.incremental.lookback_days,
                    prior_most_recent_record_utc=prior_most_recent_record_utc,
                    resolved_window_start=bundle.window_start,
                )
                logger.info(
                    'Resource %r window_start audit: %s',
                    bundle.resource_name,
                    format_window_resolution_audit(audit),
                )

                # Surface a WARNING when ``earliest_date`` is strictly
                # more recent than the lookback anchor — meaning the
                # next pull skips the interval between the latest
                # record on disk and the resolved window_start. The
                # helper returns ``None`` when no warning is warranted
                # (bootstrap, no floor, or floor at/below the
                # anchor); the orchestrator only logs when there is
                # something to say. The warning fires regardless of
                # which input wins the resolution ``max(...)`` because
                # the gap is defined by the floor's relationship to
                # the watermark, not by the resolution winner.
                gap_warning_message: str | None = (
                    format_window_resolution_gap_warning(
                        audit, resource_name=bundle.resource_name,
                    )
                )
                if gap_warning_message is not None:
                    logger.warning(gap_warning_message)

            if bundle.query is None:
                # Defensive: ``_prepare_resource_bundles`` ran before
                # this loop and sets ``query`` on every bundle. A None
                # here would mean the prepare phase skipped a bundle
                # silently — surface it loudly rather than logging
                # "resolved query parameters: None" and continuing.
                raise RuntimeError(
                    f'resource {bundle.resource_name!r}: query is None at '
                    f'process time. ResourcePreparer.build_query must run '
                    f'before _process_resource_bundles.'
                )
            logger.debug(
                'Resource %r resolved query parameters: %s',
                bundle.resource_name,
                format_resolved_query_parameters(bundle.query),
            )

            bundle.started_at_utc = self._clock.now_utc()
            resource_stopwatch: Stopwatch = Stopwatch.start(clock=self._clock)

            try:
                (
                    ResourceProcessor(bundle=bundle, client=client, clock=self._clock)
                    .execute_query()
                    .materialize_dataframe()
                    .merge_incremental()
                    .persist()
                )
            except Exception as exc:
                # ``except Exception`` is intentional: the orchestrator's
                # job at this layer is "name what failed" and re-raise.
                # Narrowing the catch would silently let some exception
                # types bypass the failure-narration log line.
                # ``logger.exception`` records ERROR level with traceback
                # — the right shape for "we are inside an except clause".
                logger.exception(
                    'Failed on resource %s: %s: %s',
                    bundle.resource_name,
                    type(exc).__name__,
                    str(exc),
                )
                raise

            resource_elapsed_seconds: float = resource_stopwatch.elapsed_seconds(
                clock=self._clock,
            )
            record_count: int = (
                len(bundle.dataframe) if bundle.dataframe is not None else 0
            )
            logger.info(
                'Wrote %s: %d records to %s (resource elapsed: %.2fs)',
                bundle.resource_name,
                record_count,
                bundle.storage_handler.data_path,
                resource_elapsed_seconds,
            )
