# src/pyholman/_pipeline/builder.py
"""
Per-bundle constructor for :class:`ResourceBundle`.

The orchestrator iterates ``user_config.resources`` and chains the
builder's named methods to assemble one bundle per resource:

    bundle = (
        ResourceBundleBuilder(resource_config, user_config, clock)
        .lookup_registry_entry()
        .construct_storage_handler()
        .compute_incremental_flags()
        .apply_window_floor()
        .build()
    )

The builder is a typed state machine: each phase is a separate
frozen, slotted dataclass carrying exactly the fields available at
that point in the chain. Each transition method returns the next
state's type, so an incomplete or out-of-order chain is a static
type error — there is no runtime check to enforce it.

State classes are defined bottom-up (terminal state first) so each
transition method's return annotation references a class already
defined; this keeps the module free of forward references.

Timing markers (``started_at_utc`` and the per-resource stopwatch)
are deliberately *not* captured here. Bundles are built up-front for
every configured resource before any processing begins, so a builder-
captured ``started_at_utc`` would be stale by the time a resource
actually starts running, and a builder-started stopwatch would be
measuring ``(this resource's elapsed) + (every prior resource's
elapsed)`` rather than just this resource. The orchestrator captures
both markers itself at the start of each resource's processing loop.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time

from pyholman._clock import Clock
from pyholman._config import UserConfig
from pyholman._config.resources import ResourceConfig
from pyholman._endpoints.registry import (
    ResourceRegistryEntry,
    get_registry_entry,
)
from pyholman._pipeline.bundle import ResourceBundle
from pyholman._storage import (
    StorageHandler,
    StorageMetadata,
    get_storage_handler,
)

__all__: list[str] = ['ResourceBundleBuilder']

logger: logging.Logger = logging.getLogger(__name__)


def _clamp_floor(
    candidate: datetime | None,
    floor: datetime | None,
) -> datetime | None:
    """
    Return ``candidate`` raised to ``floor`` when ``floor`` is later.

    The ``earliest_date`` floor is a hard lower bound on
    ``window_start``: nothing goes earlier than it regardless of any
    other input. ``max`` with ``None`` is undefined, so the helper
    discriminates the four (candidate, floor) combinations explicitly:

        - both ``None`` → ``None`` (no resolution, bootstrap with no
          inputs).
        - candidate ``None``, floor present → ``floor`` (no candidate
          but the floor stands).
        - candidate present, floor ``None`` → ``candidate`` (no floor
          to clamp by).
        - both present → ``max(candidate, floor)``.

    Used by :meth:`_BundleAfterRegistry.apply_window_floor` to compose
    the configured-filter cursor with the project floor at build time.
    :meth:`ResourcePreparer.resolve_window` does not call this helper
    directly — it takes ``max(current_window, lookback_anchor)`` and
    relies on the build-phase clamp having already raised
    ``current_window`` to the floor, so the subsequent ``max`` cannot
    fall below the floor by associativity.
    """
    if candidate is None:
        return floor
    if floor is None:
        return candidate
    return max(candidate, floor)


@dataclass(frozen=True, slots=True)
class _BundleAfterWindowFloor:
    """Terminal state. :meth:`build` assembles the :class:`ResourceBundle`."""

    resource_config: ResourceConfig
    user_config: UserConfig
    clock: Clock
    registry_entry: ResourceRegistryEntry
    storage_handler: StorageHandler
    is_incremental: bool
    is_incremental_with_prior: bool
    window_start: datetime | None

    def build(self) -> ResourceBundle:
        """
        Assemble the accumulated state into a :class:`ResourceBundle`.

        ``started_at_utc`` is left ``None``; the orchestrator's
        per-resource processing loop sets it just before invoking the
        processor chain so the value reflects when this resource
        actually started running, not when its bundle was constructed.

        Returns:
            A populated :class:`ResourceBundle` ready to flow through
            :class:`ResourcePreparer` and :class:`ResourceProcessor`.
        """
        return ResourceBundle(
            resource_name=self.resource_config.name,
            resource_config=self.resource_config,
            registry_entry=self.registry_entry,
            storage_handler=self.storage_handler,
            user_config=self.user_config,
            is_incremental=self.is_incremental,
            is_incremental_with_prior=self.is_incremental_with_prior,
            window_start=self.window_start,
        )


@dataclass(frozen=True, slots=True)
class _BundleAfterFlags:
    """State after ``compute_incremental_flags``. Exposes :meth:`apply_window_floor`."""

    resource_config: ResourceConfig
    user_config: UserConfig
    clock: Clock
    registry_entry: ResourceRegistryEntry
    storage_handler: StorageHandler
    is_incremental: bool
    is_incremental_with_prior: bool

    def apply_window_floor(self) -> _BundleAfterWindowFloor:
        """
        Compute the build-time portion of ``window_start`` and advance.

        At builder time the orchestrator has access to two of the four
        inputs that drive incremental window resolution:

            - ``user_config.incremental.earliest_date`` — the
              project-level hard floor. Promoted to a UTC midnight
              datetime so it composes with the watermark cursor.
            - ``resource_config.filters.last_change_date`` — the
              user's per-resource configured cursor. Inherited from
              :class:`IncrementalFilters`; only present when this is
              an incremental resource (snapshot filter classes reject
              the field at config validation).

        The other two inputs — the prior watermark and the configured
        ``lookback_days`` — only become relevant on
        incremental-with-prior runs and are folded in by
        :meth:`ResourcePreparer.resolve_window`. The split is
        deliberate: the build phase touches no metadata sidecar, so
        whatever is determinable from config alone is computed here
        and the prepare phase only kicks in for resources that have
        a prior cursor on disk.

        Resolution at this phase:

            - Take the user's configured filter (if any) as the
              candidate ``window_start``.
            - Clamp by the floor: if both candidate and floor are
              non-``None``, the resolved value is ``max(candidate,
              floor)``. If only one is set, that one wins. If
              neither is set, ``window_start`` stays ``None`` and
              :meth:`ResourcePreparer.resolve_window` may set it
              from the lookback anchor on a steady-state run.

        For non-incremental resources, ``window_start`` is always
        ``None`` regardless of any other input.
        """
        if not self.is_incremental:
            return _BundleAfterWindowFloor(
                resource_config=self.resource_config,
                user_config=self.user_config,
                clock=self.clock,
                registry_entry=self.registry_entry,
                storage_handler=self.storage_handler,
                is_incremental=self.is_incremental,
                is_incremental_with_prior=self.is_incremental_with_prior,
                window_start=None,
            )

        earliest_date = self.user_config.incremental.earliest_date
        floor: datetime | None = (
            None
            if earliest_date is None
            else datetime.combine(earliest_date, time.min, tzinfo=UTC)
        )
        # ``getattr`` with a ``None`` default keeps the access robust
        # to a future filter class that does not inherit
        # :class:`IncrementalFilters` — every incremental filter
        # currently does, but the orchestrator should not crash if a
        # registry change drifts.
        configured_filter_last_change_date: datetime | None = getattr(
            self.resource_config.filters,
            'last_change_date',
            None,
        )
        window_start: datetime | None = _clamp_floor(
            candidate=configured_filter_last_change_date,
            floor=floor,
        )

        return _BundleAfterWindowFloor(
            resource_config=self.resource_config,
            user_config=self.user_config,
            clock=self.clock,
            registry_entry=self.registry_entry,
            storage_handler=self.storage_handler,
            is_incremental=self.is_incremental,
            is_incremental_with_prior=self.is_incremental_with_prior,
            window_start=window_start,
        )


@dataclass(frozen=True, slots=True)
class _BundleAfterHandler:
    """State after ``construct_storage_handler``. Exposes :meth:`compute_incremental_flags`."""

    resource_config: ResourceConfig
    user_config: UserConfig
    clock: Clock
    registry_entry: ResourceRegistryEntry
    storage_handler: StorageHandler

    def compute_incremental_flags(self) -> _BundleAfterFlags:
        """
        Compute ``is_incremental`` and ``is_incremental_with_prior`` and advance.

        Reads ``resource_config.incremental`` for the static flag (the
        snapshot-only resource variants enforce this is ``False`` at
        config validation; ``getattr`` with a ``False`` default keeps
        the formulation robust to a future variant that omits the
        field). For incremental resources, consults the storage
        handler's cached metadata read to decide
        ``is_incremental_with_prior``. Snapshot resources skip the
        metadata read entirely — the second flag is locked at ``False``
        either way and the read would be wasted I/O.

        Side Effects:
            Triggers the storage handler's metadata cache to populate
            on disk-read for incremental resources. Subsequent reads
            on the same handler instance use the cached value.
        """
        is_incremental: bool = bool(getattr(self.resource_config, 'incremental', False))

        if not is_incremental:
            is_incremental_with_prior: bool = False
        else:
            prior_metadata: StorageMetadata | None = (
                self.storage_handler.read_metadata()
            )
            is_incremental_with_prior = prior_metadata is not None

        return _BundleAfterFlags(
            resource_config=self.resource_config,
            user_config=self.user_config,
            clock=self.clock,
            registry_entry=self.registry_entry,
            storage_handler=self.storage_handler,
            is_incremental=is_incremental,
            is_incremental_with_prior=is_incremental_with_prior,
        )


@dataclass(frozen=True, slots=True)
class _BundleAfterRegistry:
    """State after ``lookup_registry_entry``. Exposes :meth:`construct_storage_handler`."""

    resource_config: ResourceConfig
    user_config: UserConfig
    clock: Clock
    registry_entry: ResourceRegistryEntry

    def construct_storage_handler(self) -> _BundleAfterHandler:
        """
        Construct the configured concrete storage handler and advance.

        Reads :attr:`UserConfig.output` for format and compression and
        :attr:`UserConfig.working_directory` for the parent directory.
        """
        storage_handler: StorageHandler = get_storage_handler(
            output_config=self.user_config.output,
            working_directory=self.user_config.working_directory,
            resource_name=self.resource_config.name,
        )
        return _BundleAfterHandler(
            resource_config=self.resource_config,
            user_config=self.user_config,
            clock=self.clock,
            registry_entry=self.registry_entry,
            storage_handler=storage_handler,
        )


@dataclass(frozen=True, slots=True)
class ResourceBundleBuilder:
    """
    Initial state of the bundle-construction state machine.

    Holds the three construction-time inputs and exposes the first
    transition. Subsequent states are file-private; callers reach
    them only through the chained return values.

    Args:
        resource_config: The discriminated-union variant for this
            resource, taken from ``user_config.resources``.
        user_config: The full :class:`UserConfig`. Later transitions
            read ``user_config.output`` for storage-handler
            construction and ``user_config.incremental`` for the
            optional ``earliest_date`` floor; the bundle stores the
            reference for later stages.
        clock: Time provider. Stored on each builder state for
            symmetry with the rest of the pipeline; the builder
            itself does not currently call into it. The orchestrator
            captures per-resource timing against its own clock.
    """

    resource_config: ResourceConfig
    user_config: UserConfig
    clock: Clock

    def lookup_registry_entry(self) -> _BundleAfterRegistry:
        """Resolve the resource's registry entry and advance the state."""
        registry_entry: ResourceRegistryEntry = get_registry_entry(
            self.resource_config.name,
        )
        return _BundleAfterRegistry(
            resource_config=self.resource_config,
            user_config=self.user_config,
            clock=self.clock,
            registry_entry=registry_entry,
        )
