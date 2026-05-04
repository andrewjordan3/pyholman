# src/pyholman/_pipeline/processor.py
"""
Per-bundle processing chain: API call, dataframe materialization, merge, persist.

:class:`ResourceProcessor` is the third pipeline phase, run after a
:class:`ResourcePreparer` chain finishes. The orchestrator opens a
:class:`HolmanClient` once for the run and constructs one processor
per bundle. Each method mutates ``self._bundle`` in place and returns
``self`` for chaining.
"""

import logging
from datetime import datetime
from typing import Self

import pandas as pd

from pyholman._client import HolmanClient
from pyholman._clock import Clock
from pyholman._dataframe_tools import deduplicate_dataframe
from pyholman._pipeline.bundle import ResourceBundle
from pyholman._pipeline.filter_safety import hash_filter_model
from pyholman._pipeline.incremental_state import IncrementalStateCorruptedError
from pyholman._storage import (
    CsvHandler,
    StorageMetadata,
    StorageRunMode,
    compute_most_recent_record_utc,
    get_pyholman_version,
    replace_window,
)

__all__: list[str] = ['ResourceProcessor']

logger: logging.Logger = logging.getLogger(__name__)


class ResourceProcessor:
    """
    Per-bundle processing chain.

    Each method mutates ``self._bundle`` in place and returns ``self``
    for chaining. The ``persist`` step writes data first and metadata
    second so a partial failure leaves either the prior state intact
    (data write failed) or stale metadata pointing at last run's data
    file (metadata write failed). The latter is recoverable on the
    next run because the hash check or window resolution will read
    the stale metadata and either pass cleanly or fail loudly.

    Args:
        bundle: The :class:`ResourceBundle` produced by the preparer.
            Mutated in place by every method on this class.
        client: A live, authenticated :class:`HolmanClient`. The
            processor does not own the client lifecycle — the caller
            opened it via context manager and will close it.
        clock: Time provider for ``persist`` to stamp
            :attr:`StorageMetadata.run_completed_utc`.
    """

    __slots__ = ('_bundle', '_client', '_clock')

    def __init__(
        self,
        *,
        bundle: ResourceBundle,
        client: HolmanClient,
        clock: Clock,
    ) -> None:
        self._bundle: ResourceBundle = bundle
        self._client: HolmanClient = client
        self._clock: Clock = clock

    def execute_query(self) -> Self:
        """
        Issue the prepared query and collect every page into ``records``.

        Side Effects:
            Sets ``self._bundle.records``. Issues HTTP requests via
            the supplied client.

        Raises:
            RuntimeError: If :meth:`ResourcePreparer.build_query` was
                not run on the bundle first.
            HolmanError, TransientHolmanError, RateLimitError:
                Propagated from the client unchanged.
        """
        if self._bundle.query is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r}: ResourcePreparer.'
                f'build_query must run before ResourceProcessor.execute_query.'
            )
        self._bundle.records = self._client.collect(self._bundle.query)
        logger.debug(
            'Resource %r: collected %d record(s).',
            self._bundle.resource_name,
            len(self._bundle.records),
        )
        return self

    def materialize_dataframe(self) -> Self:
        """
        Convert ``records`` to a deduplicated DataFrame.

        Logs an INFO line documenting the dedup result every time —
        even when nothing was removed — so a reader of the log can
        always tell whether dedup ran and what it did. Holman returns
        repeated records on some endpoints (heavily on ``contacts``);
        a silent step here turned the resulting row drop into a
        mystery shrink in the run log.

        Side Effects:
            Sets ``self._bundle.dataframe``. Empty input is allowed at
            this stage; the empty-write rejection lives in
            :meth:`persist`, which is the locked design boundary —
            the storage handler refuses to write an empty DataFrame.

        Raises:
            RuntimeError: If :meth:`execute_query` was not run first.
        """
        if self._bundle.records is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r}: execute_query '
                f'must run before materialize_dataframe.'
            )

        response_class = self._bundle.registry_entry.response_class
        raw: pd.DataFrame = response_class.records_to_dataframe(self._bundle.records)
        input_rows: int = len(raw)
        self._bundle.dataframe = deduplicate_dataframe(raw)
        output_rows: int = len(self._bundle.dataframe)
        removed_rows: int = input_rows - output_rows
        duplicate_rate: float = (
            (removed_rows / input_rows * 100.0) if input_rows > 0 else 0.0
        )
        logger.info(
            'Resource %r deduplicated: input_rows=%d output_rows=%d '
            'removed_rows=%d duplicate_rate=%.2f%%',
            self._bundle.resource_name,
            input_rows,
            output_rows,
            removed_rows,
            duplicate_rate,
        )
        return self

    def merge_incremental(self) -> Self:
        """
        For incremental-with-prior runs, replace the window with new rows.

        Snapshot resources and first-time incremental runs short-circuit
        to a no-op — the dataframe set by :meth:`materialize_dataframe`
        is already the final write payload.

        For incremental-with-prior runs:

            - Load the existing dataframe via
              ``storage_handler.to_dataframe()``. The existing data is
              already deduplicated from the prior write — do not dedup
              it again, that would risk rewriting user-relevant rows.
            - When the storage handler is CSV-backed, coerce the
              watermark column to tz-aware UTC datetime. CSV is lossy
              for dtypes (the column comes back as object/str) and
              :func:`replace_window` requires a datetime-typed column
              for the window comparison. Parquet preserves dtypes and
              is left untouched — a non-datetime watermark from
              Parquet indicates an upstream contract violation that
              must surface loudly.
            - Call :func:`replace_window` to drop existing rows whose
              watermark is at or after ``bundle.window_start`` and
              concat the freshly fetched rows.
            - Store the merged result on ``bundle.dataframe``. Do not
              dedup the result — existing was deduped, new was deduped
              in :meth:`materialize_dataframe`, the union under
              ``replace_window`` cannot introduce duplicates.

        Side Effects:
            For incremental-with-prior, replaces ``self._bundle.dataframe``
            with the merged result.

        Raises:
            RuntimeError: If :meth:`materialize_dataframe` was not run
                first, or if the registry entry's response class
                declares no ``watermark_column`` for an incremental
                resource (which would indicate a registry / response
                drift bug — caught by the registry validator at
                import time, but the runtime check costs nothing).
            IncrementalStateCorruptedError: If the storage handler is
                CSV-backed and the watermark column on disk contains
                values that cannot be parsed as datetimes. Means the
                CSV was hand-edited or corrupted between runs; the
                error names the file and prescribes the recovery.
        """
        if not self._bundle.is_incremental_with_prior:
            return self

        if self._bundle.dataframe is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r}: '
                f'materialize_dataframe must run before merge_incremental.'
            )

        watermark_column: str | None = (
            self._bundle.registry_entry.response_class.watermark_column
        )
        if watermark_column is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r}: '
                f'is_incremental_with_prior=True but the response class '
                f'declares no watermark_column. Registry / response '
                f'drift.'
            )

        if self._bundle.window_start is None:
            raise RuntimeError(
                f'resource {self._bundle.resource_name!r}: '
                f'is_incremental_with_prior=True but window_start is None '
                f'after resolve_window. Pipeline ordering bug.'
            )

        existing: pd.DataFrame = self._bundle.storage_handler.to_dataframe()
        # Format-discrimination via ``isinstance`` rather than promoting
        # ``_format_label`` to a public Protocol attribute: the dtype
        # coercion is a CSV-specific workaround for CSV's lossy
        # round-trip, not a general "format identity" feature, and the
        # Protocol stays free of attributes that exist only to flag
        # one concrete handler.
        if isinstance(self._bundle.storage_handler, CsvHandler):
            existing = self._coerce_csv_watermark_column(
                existing=existing,
                watermark_column=watermark_column,
            )

        merged: pd.DataFrame = replace_window(
            existing=existing,
            new=self._bundle.dataframe,
            watermark_column=watermark_column,
            window_start=self._bundle.window_start,
        )
        self._bundle.dataframe = merged
        return self

    def _coerce_csv_watermark_column(
        self,
        existing: pd.DataFrame,
        watermark_column: str,
    ) -> pd.DataFrame:
        """
        Coerce ``watermark_column`` to tz-aware UTC datetime, in place on a copy.

        Every value pyholman itself writes is round-trippable (Pydantic
        validates the watermark as ``datetime | None`` before it reaches
        the DataFrame; ``to_csv`` serializes datetimes as ISO 8601). A
        parse failure therefore means the CSV was hand-edited or
        corrupted between runs — silent rescue (``errors='coerce'``)
        would hide that and keep the broken row forever, never
        refreshing it. We raise instead with a typed exception that
        names the file and prescribes the recovery.

        Args:
            existing: DataFrame loaded from the CSV data file.
            watermark_column: Name of the column to coerce.

        Returns:
            ``existing`` with ``watermark_column`` typed as tz-aware
            UTC datetime. The result is a pipeline-local DataFrame; the
            on-disk CSV is not rewritten.

        Raises:
            IncrementalStateCorruptedError: If any value in the column
                fails to parse.
        """
        try:
            existing[watermark_column] = pd.to_datetime(
                existing[watermark_column],
                utc=True,
                errors='raise',
            )
        except (ValueError, TypeError) as parse_error:
            raise IncrementalStateCorruptedError(
                resource_name=self._bundle.resource_name,
                file_path=self._bundle.storage_handler.data_path,
                watermark_column=watermark_column,
            ) from parse_error
        return existing

    def persist(self) -> Self:
        """
        Write the dataframe and metadata sidecar.

        Data is written first, metadata second. A partial failure
        therefore leaves either:

            - The old state intact (data write failed; the storage
              handler's atomic write guarantees no partial file).
            - Stale metadata pointing at last run's data file
              (metadata write failed). Recoverable on the next run.

        Branches on the response model's ``watermark_column``:

            - ``watermark_column is None`` (snapshot endpoint):
              construct via :meth:`StorageMetadata.for_snapshot`. Run
              mode is locked to ``FULL_REFRESH`` and
              ``most_recent_record_utc`` is ``None``; both are filled
              in by the factory.
            - ``watermark_column is not None`` (incremental-capable
              endpoint): compute the newest record's anchor via
              :func:`compute_most_recent_record_utc` and construct via
              :meth:`StorageMetadata.for_incremental`. Run mode reflects
              the resource's *configuration*, not the run's effect: a
              first-time-incremental run reports ``INCREMENTAL`` even
              though it writes a full snapshot.

        Side Effects:
            Writes the data file, then the metadata sidecar, via
            ``self._bundle.storage_handler``. Reads the wall clock
            via ``self._clock.now_utc()`` for ``run_completed_utc``.

        Raises:
            RuntimeError: If :meth:`materialize_dataframe` (or
                :meth:`merge_incremental`) was not run first.
            ValueError: From the storage handler when the dataframe
                is empty. Empty results are a locked failure mode —
                a successful run cannot stamp metadata under
                ``record_count=0``.
        """
        bundle: ResourceBundle = self._bundle
        if bundle.dataframe is None:
            raise RuntimeError(
                f'resource {bundle.resource_name!r}: materialize_dataframe '
                f'must run before persist.'
            )
        if bundle.started_at_utc is None:
            # The orchestrator's per-resource processing loop is
            # responsible for stamping ``started_at_utc`` just before
            # invoking the processor chain. A None here means a caller
            # bypassed that step and is calling the processor directly
            # without having captured the wall-clock start; the metadata
            # ``run_started_utc`` field has nowhere safe to fall back to.
            raise RuntimeError(
                f'resource {bundle.resource_name!r}: started_at_utc is None '
                f'at persist time. The orchestrator must set it before the '
                f'processor chain runs.'
            )
        started_at_utc: datetime = bundle.started_at_utc

        watermark_column: str | None = (
            bundle.registry_entry.response_class.watermark_column
        )
        run_completed_utc = self._clock.now_utc()
        record_count: int = len(bundle.dataframe)
        filters_hash: str = hash_filter_model(bundle.resource_config.filters)

        metadata: StorageMetadata
        if watermark_column is None:
            metadata = StorageMetadata.for_snapshot(
                endpoint=bundle.resource_name,
                pyholman_version=get_pyholman_version(),
                run_started_utc=started_at_utc,
                run_completed_utc=run_completed_utc,
                record_count=record_count,
                output_format=bundle.user_config.output.format,
                compression=bundle.user_config.output.compression,
                filters_hash=filters_hash,
            )
        else:
            most_recent_record_utc = compute_most_recent_record_utc(
                bundle.dataframe,
                watermark_column,
            )
            run_mode: StorageRunMode = (
                StorageRunMode.INCREMENTAL
                if bundle.is_incremental
                else StorageRunMode.FULL_REFRESH
            )
            metadata = StorageMetadata.for_incremental(
                endpoint=bundle.resource_name,
                pyholman_version=get_pyholman_version(),
                run_mode=run_mode,
                run_started_utc=started_at_utc,
                run_completed_utc=run_completed_utc,
                most_recent_record_utc=most_recent_record_utc,
                record_count=record_count,
                output_format=bundle.user_config.output.format,
                compression=bundle.user_config.output.compression,
                filters_hash=filters_hash,
            )

        # Data first; if this raises (e.g., empty dataframe), no
        # metadata is written and the prior data file is intact.
        bundle.storage_handler.from_dataframe(bundle.dataframe)
        bundle.storage_handler.write_metadata(metadata)
        logger.info(
            'Resource %r persisted: rows=%d run_mode=%s.',
            bundle.resource_name,
            record_count,
            metadata.run_mode.value,
        )
        return self
