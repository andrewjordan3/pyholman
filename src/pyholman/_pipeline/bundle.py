# src/pyholman/_pipeline/bundle.py
"""
Per-resource state container flowing through the pipeline.

:class:`ResourceBundle` is the only mutable state-tracker in the
pipeline. Everything else is functions or short-lived helper objects
(``ResourceBundleBuilder``, ``ResourcePreparer``, ``ResourceProcessor``)
that read from and mutate one bundle in place. The orchestrator iterates
bundles per-resource so a bundle that completes ``persist`` is on disk
regardless of whether a later resource fails.
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from pyholman._config import UserConfig
from pyholman._config.resources import ResourceConfig
from pyholman._core import QueryInputBase, ResponseModel
from pyholman._endpoints.registry import EndpointName, ResourceRegistryEntry
from pyholman._storage import StorageHandler

__all__: list[str] = ['ResourceBundle']


@dataclass(slots=True)
class ResourceBundle:
    """
    Per-resource state flowing through the pipeline.

    Constructed by :class:`ResourceBundleBuilder` with the
    construction-time fields populated. Pipeline stages mutate the
    optional fields as work progresses. The orchestrator iterates
    bundles per-resource; a bundle that completes ``persist`` is on
    disk before the next bundle is touched.

    Attributes:
        resource_name: Registered resource name; matches
            ``resource_config.name`` and ``registry_entry.name``.
        resource_config: The user's discriminated-union variant for
            this resource (filters, ``incremental`` flag, etc.).
        registry_entry: The resource's registry entry — query class,
            response class, ``supports_incremental`` flag.
        storage_handler: The configured concrete handler
            (Parquet or CSV) for this resource. Owns the data file
            path, the metadata sidecar path, and the format-specific
            serialization.
        user_config: The full :class:`UserConfig`. Downstream stages
            access whatever sections they need (``user_config.api``,
            ``user_config.output``, ``user_config.incremental``,
            etc.); a single reference is cheaper than threading
            individual sections through the bundle.
        is_incremental: Precomputed at build time; ``True`` when the
            resource's config has ``incremental=True``. Stages
            short-circuit on this rather than re-deriving.
        is_incremental_with_prior: Precomputed at build time.
            ``True`` only when ``is_incremental`` and
            ``storage_handler.read_metadata()`` returned a non-None
            sidecar at build time. The handler's metadata cache means
            that read is shared across this builder pass and any
            later read in :class:`ResourcePreparer`.
        started_at_utc: Wall-clock UTC instant for this resource's
            processing start. ``None`` until the orchestrator's
            per-resource processing loop sets it (just before invoking
            the processor chain). Set then rather than at builder
            time so :attr:`StorageMetadata.run_started_utc` reflects
            the moment the resource actually started running, not the
            moment its bundle was constructed up-front. The processor's
            ``persist`` step requires it to be non-None.
        window_start: Inclusive lower bound applied to the watermark
            filter. ``None`` for snapshot resources, for incremental
            resources with no ``earliest_date`` floor and no prior
            metadata, or for incremental resources before
            :meth:`ResourcePreparer.resolve_window` runs. Set at
            build time from the floor; updated by
            :meth:`ResourcePreparer.resolve_window` for
            incremental-with-prior resources.
        query: The fully-built query the client will issue. Set by
            :meth:`ResourcePreparer.build_query`; ``None`` until
            then.
        records: The collected response items. Set by
            :meth:`ResourceProcessor.execute_query`; ``None`` until
            then.
        dataframe: The materialized DataFrame.
            :meth:`ResourceProcessor.materialize_dataframe` sets it
            from ``records``; :meth:`ResourceProcessor.merge_incremental`
            replaces it with the windowed merge for
            incremental-with-prior runs.
    """

    resource_name: EndpointName
    resource_config: ResourceConfig
    registry_entry: ResourceRegistryEntry
    storage_handler: StorageHandler
    user_config: UserConfig
    is_incremental: bool
    is_incremental_with_prior: bool
    window_start: datetime | None

    started_at_utc: datetime | None = None
    query: QueryInputBase[ResponseModel] | None = None
    records: list[ResponseModel] | None = None
    dataframe: pd.DataFrame | None = None
