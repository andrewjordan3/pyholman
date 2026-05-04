# src/pyholman/_pipeline/preparer.py
"""
Per-bundle preparation chain: filter-hash check, window resolution, query construction.

:class:`ResourcePreparer` is one of the three pipeline phases. It runs
no network I/O — every operation is either a cached metadata read
through the storage handler or pure data manipulation. Each method
short-circuits cleanly for resources where the operation does not
apply (snapshot-only, first-time incremental).
"""

import logging
from datetime import timedelta
from typing import Self

from pyholman._core import IncrementalFilters
from pyholman._endpoints.query_builder import build_query_from_filters
from pyholman._pipeline.bundle import ResourceBundle
from pyholman._pipeline.filter_safety import (
    FilterHashMismatchError,
    hash_filter_model,
    verify_filter_hash_matches,
)
from pyholman._storage import StorageMetadata

__all__: list[str] = ['ResourcePreparer']

logger: logging.Logger = logging.getLogger(__name__)

# Issue tracker URL stamped into internal-invariant-violation error
# messages so a user encountering one has a place to report it without
# reading source. Mirrored from ``[project.urls].Issues`` in
# ``pyproject.toml``; if either ever changes, both sites must update.
_PYHOLMAN_ISSUES_URL: str = 'https://github.com/andrewjordan3/pyholman/issues'


class ResourcePreparer:
    """
    Per-bundle preparation chain.

    Each method mutates ``self._bundle`` in place and returns ``self``
    for chaining. Methods are designed to be called in order; calling
    :meth:`resolve_window` before :meth:`verify_filter_hash` is
    technically legal but defeats the fail-fast intent — the hash check
    is the cheapest failure mode.

    Args:
        bundle: The :class:`ResourceBundle` produced by
            :class:`ResourceBundleBuilder`. Mutated in place by every
            method on this class.
    """

    __slots__ = ('_bundle',)

    def __init__(self, *, bundle: ResourceBundle) -> None:
        self._bundle: ResourceBundle = bundle

    def verify_filter_hash(self) -> Self:
        """
        Reject mismatched filter hashes for incremental-with-prior runs.

        Short-circuits to a no-op for snapshot resources and for
        first-time incremental runs (no prior metadata to compare
        against). For incremental-with-prior runs, the prior metadata
        sidecar's :attr:`StorageMetadata.filters_hash` must match the
        hash computed from ``bundle.resource_config.filters`` — the
        original user-configured filters, not any windowed variant.

        Side Effects:
            None on disk. Reads the cached metadata via the storage
            handler.

        Raises:
            FilterHashMismatchError: If the existing hash on the
                sidecar differs from the new hash computed for the
                current run.
        """
        if not self._bundle.is_incremental_with_prior:
            return self

        prior_metadata: StorageMetadata | None = (
            self._bundle.storage_handler.read_metadata()
        )
        if prior_metadata is None:
            # Defensive: ``is_incremental_with_prior`` was set True at
            # build time, but the cached metadata read returned None
            # here. Either the storage handler's metadata cache was
            # mutated between phases (a concurrent modification of
            # the working directory), or pyholman has a bug in its
            # incremental-state tracking. Raise loudly so the bug
            # surfaces rather than silently falling through.
            #
            # The user cannot recover from this by themselves — the
            # message is framed as an internal invariant violation
            # and points at the issue tracker rather than at a
            # filesystem action. Match the resource-and-path naming
            # idiom of :class:`FilterHashMismatchError` /
            # :class:`IncrementalStateCorruptedError` so a maintainer
            # reading the report has the same context to start from.
            raise RuntimeError(
                f'Internal invariant violation in pyholman: resource '
                f'{self._bundle.resource_name!r} was flagged as having '
                f'prior metadata at bundle-build time, but the storage '
                f'handler at '
                f'{self._bundle.storage_handler.metadata_path} now '
                f'returns no metadata. This indicates either a concurrent '
                f'modification of the working directory between bundle '
                f'construction and resource processing, or a bug in '
                f"pyholman's incremental state tracking. Please file an "
                f'issue at {_PYHOLMAN_ISSUES_URL} with the resource name, '
                f'working directory contents, and any recent steps that '
                f'may have modified the working directory.'
            )

        new_hash: str = hash_filter_model(self._bundle.resource_config.filters)
        try:
            verify_filter_hash_matches(
                prior_metadata,
                new_hash,
                data_path=self._bundle.storage_handler.data_path,
            )
        except FilterHashMismatchError as mismatch_error:
            # The exception message itself already names the resource,
            # the on-disk path, the existing and new hash fingerprints,
            # and the recovery action; ``logger.error`` here surfaces the
            # full text at ERROR level so a user with INFO-or-coarser
            # logging still sees what happened. ``%s`` interpolates
            # the rendered message rather than the type repr.
            logger.error('%s', mismatch_error)
            raise
        return self

    def resolve_window(self) -> Self:
        """
        Update :attr:`ResourceBundle.window_start` for incremental-with-prior runs.

        Snapshot resources never get a window — short-circuit. First-time
        incremental runs (no prior metadata) keep whatever
        :meth:`_BundleAfterRegistry.apply_window_floor` set from the
        configured ``earliest_date`` floor and the configured
        ``filters.last_change_date`` cursor (or ``None`` if neither
        was set). For incremental-with-prior runs:

            - Read prior metadata via the cached handler.
            - Compute ``lookback_anchor = most_recent_record_utc - lookback_days``.
            - If the bundle's current ``window_start`` is ``None``,
              set it to ``lookback_anchor``. Otherwise, take the
              maximum so neither the configured floor nor a more-recent
              configured filter lets the window slide earlier than its
              bound. The build-phase clamp guarantees the floor is
              already baked into the current value, so a subsequent
              ``max`` with ``lookback_anchor`` cannot fall below the
              floor by associativity.

        Side Effects:
            Updates ``self._bundle.window_start`` for
            incremental-with-prior runs. Reads no disk.

        Raises:
            RuntimeError: If ``most_recent_record_utc`` is ``None`` on
                prior metadata while ``is_incremental_with_prior`` is
                ``True``. That state is unreachable in normal operation
                (empty results raise before any metadata stamp); a
                loud failure beats silent re-pulling everything.
        """
        if not self._bundle.is_incremental:
            return self

        if not self._bundle.is_incremental_with_prior:
            return self

        prior_metadata: StorageMetadata | None = (
            self._bundle.storage_handler.read_metadata()
        )
        if prior_metadata is None or prior_metadata.most_recent_record_utc is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r} is flagged '
                f'is_incremental_with_prior=True but the prior metadata '
                f'sidecar at '
                f'{self._bundle.storage_handler.metadata_path} carries '
                f'no most_recent_record_utc anchor. The storage handler '
                f'rejects empty writes upstream, so this state indicates '
                f'a corrupted sidecar.'
            )

        lookback_days: int = self._bundle.user_config.incremental.lookback_days
        lookback_anchor = prior_metadata.most_recent_record_utc - timedelta(
            days=lookback_days
        )

        current_window: object = self._bundle.window_start
        if current_window is None:
            self._bundle.window_start = lookback_anchor
        else:
            assert isinstance(current_window, type(lookback_anchor)), (
                'window_start type drift'
            )
            self._bundle.window_start = max(current_window, lookback_anchor)
        return self

    def build_query(self) -> Self:
        """
        Apply the resolved window to filters and construct the typed query.

        For incremental resources whose filter model is an
        :class:`IncrementalFilters` subclass and whose ``window_start``
        is non-``None``, the filters are rewritten via
        :meth:`IncrementalFilters.with_window_start` before being
        passed to :func:`build_query_from_filters`. For snapshot
        resources or when no window override applies, the original
        filters are passed through unchanged (which itself may be
        ``None`` for endpoints with no configured filters).

        Side Effects:
            Sets ``self._bundle.query``. Reads no disk and issues no
            HTTP request.

        Raises:
            AssertionError: Defensive — if ``window_start`` is
                non-None for a registry entry whose
                ``supports_incremental`` is ``False``, or for a
                filter model that is not an
                :class:`IncrementalFilters` subclass. Indicates a
                registry / filter-model wiring bug, not a user error.
        """
        bundle: ResourceBundle = self._bundle
        filters = bundle.resource_config.filters

        if (
            bundle.is_incremental
            and bundle.window_start is not None
            and filters is not None
        ):
            assert bundle.registry_entry.supports_incremental, (
                f'window_start was resolved for resource '
                f'{bundle.resource_name!r} but the registry entry says '
                f'supports_incremental=False'
            )
            assert isinstance(filters, IncrementalFilters), (
                f'resource {bundle.resource_name!r} has incremental=True '
                f'but its filter model is not an IncrementalFilters '
                f'subclass'
            )
            filters = filters.with_window_start(bundle.window_start)

        bundle.query = build_query_from_filters(
            registry_entry=bundle.registry_entry,
            filters=filters,
            api_config=bundle.user_config.api,
            fleet_config=bundle.user_config.fleet,
        )
        return self
