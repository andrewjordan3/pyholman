# src/pyholman/_storage/metadata/model.py
"""
Sidecar metadata describing a single pyholman write.

A ``StorageMetadata`` instance records the *what* of a persisted file —
endpoint, run mode, timestamps, record count, output format and
compression — so downstream jobs and humans can answer "when was this
data last refreshed" and "was it a full refresh or incremental" without
reading the data file itself. Metadata is written as a JSON sidecar
alongside the data file; neither the Parquet nor the CSV handler touches
the sidecar directly — the write is explicit, separate, and the caller's
responsibility.
"""

import logging
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from atomicwrites import atomic_write
from pydantic import AwareDatetime, Field, field_validator, model_validator

from pyholman._config import OutputFormat, ParquetCompression
from pyholman._core import FrozenModel

__all__: list[str] = [
    'StorageMetadata',
    'StorageRunMode',
]

logger: logging.Logger = logging.getLogger(__name__)

# SHA-256 digests are exactly 64 lowercase hex characters. Anything else
# in ``filters_hash`` means the sidecar was hand-edited, truncated,
# written by a non-pyholman tool, or corrupted — none of those should
# silently round-trip through ``StorageMetadata``.
_FILTERS_HASH_PATTERN: re.Pattern[str] = re.compile(r'[0-9a-f]{64}')


class StorageRunMode(StrEnum):
    """
    How the run that produced this file was executed.

    Members:
        FULL_REFRESH: The entire target dataset was re-fetched and the
            output file was written from scratch.
        INCREMENTAL: Only records modified since a prior watermark were
            fetched; the output file is the result of merging those new
            rows into the previously persisted file.
    """

    FULL_REFRESH = 'full_refresh'
    INCREMENTAL = 'incremental'


class StorageMetadata(FrozenModel):
    """
    Immutable description of a single pyholman write.

    Construction:
        Prefer the factory classmethods over the base constructor —
        they make the snapshot-vs-incremental distinction explicit and
        enforce the additional rules each branch needs.

        - :meth:`for_snapshot` for snapshot-only endpoints (no per-record
          watermark; ``most_recent_record_utc`` is always ``None``;
          ``run_mode`` is always ``FULL_REFRESH``).
        - :meth:`for_incremental` for incremental-capable endpoints
          (``most_recent_record_utc`` must be set whenever
          ``record_count > 0``).

    All ``datetime`` fields must be timezone-aware UTC. Naive datetimes
    are rejected at validation time. Cross-field rules enforced by model
    validators:

        - ``run_completed_utc`` is never earlier than ``run_started_utc``.
        - ``record_count == 0`` implies ``most_recent_record_utc is None``.
          (The reverse — ``record_count > 0`` with a ``None`` anchor —
          is legal at the base model because snapshot endpoints
          legitimately persist non-empty data without a record-level
          anchor; the "non-empty implies non-None anchor" rule lives on
          :meth:`for_incremental` where it correctly applies.)

    Attributes:
        endpoint: Short identifier of the Holman endpoint that produced
            the data (e.g., ``'vehicles'``, ``'maintenance'``).
        pyholman_version: Version of the pyholman package that performed
            the write. Callers obtain this via
            :func:`pyholman._storage.metadata.version.get_pyholman_version`;
            the value ``'unknown'`` is acceptable and occurs in
            non-installed dev environments.
        run_mode: Whether the run was a full refresh or an incremental
            update.
        run_started_utc: UTC timestamp when the run began.
        run_completed_utc: UTC timestamp when the run finished. Must be
            greater than or equal to ``run_started_utc``.
        most_recent_record_utc: The maximum watermark value across the
            persisted rows, or ``None`` when the file is empty.
        record_count: Number of rows in the persisted file.
            Non-negative.
        output_format: Serialization format of the data file
            (``OutputFormat.PARQUET`` or ``OutputFormat.CSV``).
        compression: Parquet compression codec, or ``None`` for
            uncompressed output. Callers using CSV should pass ``None``.
        filters_hash: SHA-256 hex digest of the filter model in effect
            for this write (64 lowercase hex characters, no prefix).
            Always present — a full-refresh run with an empty filter
            model still hashes to a valid digest (the SHA-256 of
            ``{}``), and future refreshes compare cleanly against it.
            The orchestrator reads this back before an incremental
            run and refuses to proceed if the stored hash does not
            match the current configuration's hash; see
            :func:`pyholman._pipeline.filter_safety.verify_filter_hash_matches`.
    """

    endpoint: str
    pyholman_version: str
    run_mode: StorageRunMode
    run_started_utc: AwareDatetime
    run_completed_utc: AwareDatetime
    most_recent_record_utc: AwareDatetime | None
    record_count: int = Field(ge=0)
    output_format: OutputFormat
    compression: ParquetCompression | None
    filters_hash: str

    @field_validator('filters_hash')
    @classmethod
    def _validate_filters_hash_shape(cls, value: str) -> str:
        if _FILTERS_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError(
                f'filters_hash must be exactly 64 lowercase hex characters; '
                f'got {value!r}'
            )
        return value

    @model_validator(mode='after')
    def _check_completion_not_before_start(self) -> Self:
        if self.run_completed_utc < self.run_started_utc:
            raise ValueError(
                f'run_completed_utc ({self.run_completed_utc.isoformat()}) '
                f'must not be earlier than run_started_utc '
                f'({self.run_started_utc.isoformat()}).'
            )
        return self

    @model_validator(mode='after')
    def _check_record_count_and_most_recent_consistency(self) -> Self:
        if self.record_count == 0 and self.most_recent_record_utc is not None:
            raise ValueError(
                'record_count is 0 but most_recent_record_utc is set; '
                'empty files must have most_recent_record_utc=None.'
            )
        # The reverse direction — ``record_count > 0`` with
        # ``most_recent_record_utc is None`` — is legal at the base
        # model: snapshot-only endpoints declare no watermark column
        # and persist non-empty data with no record-level anchor. The
        # "non-empty implies non-None anchor" check still exists, but
        # only on :meth:`StorageMetadata.for_incremental` where it
        # correctly applies; constructions for snapshot endpoints go
        # through :meth:`StorageMetadata.for_snapshot` and bypass it.
        return self

    @classmethod
    def for_snapshot(  # noqa: PLR0913 — kwargs mirror StorageMetadata fields; bundling them into a dataclass would duplicate the model itself without saving anything.
        cls,
        *,
        endpoint: str,
        pyholman_version: str,
        run_started_utc: datetime,
        run_completed_utc: datetime,
        record_count: int,
        output_format: OutputFormat,
        compression: ParquetCompression | None,
        filters_hash: str,
    ) -> Self:
        """
        Construct metadata for a snapshot-only endpoint.

        Snapshot endpoints declare no per-record watermark, so the
        ``most_recent_record_utc`` anchor is always ``None``. Run mode
        is always :attr:`StorageRunMode.FULL_REFRESH` because snapshot
        endpoints cannot be incrementally updated. Both are filled in
        by the factory; callers do not pass them.

        Args:
            endpoint: Short identifier of the Holman endpoint that
                produced the data.
            pyholman_version: Version string captured by
                :func:`pyholman._storage.metadata.version.get_pyholman_version`.
            run_started_utc: UTC timestamp when the run began.
            run_completed_utc: UTC timestamp when the run finished.
            record_count: Number of rows in the persisted file.
            output_format: Serialization format of the data file.
            compression: Parquet compression codec (or ``None`` for
                CSV / uncompressed Parquet).
            filters_hash: SHA-256 hex digest of the filter model.

        Returns:
            A validated :class:`StorageMetadata` instance with
            ``most_recent_record_utc=None`` and
            ``run_mode=StorageRunMode.FULL_REFRESH``.
        """
        return cls(
            endpoint=endpoint,
            pyholman_version=pyholman_version,
            run_mode=StorageRunMode.FULL_REFRESH,
            run_started_utc=run_started_utc,
            run_completed_utc=run_completed_utc,
            most_recent_record_utc=None,
            record_count=record_count,
            output_format=output_format,
            compression=compression,
            filters_hash=filters_hash,
        )

    @classmethod
    def for_incremental(  # noqa: PLR0913 — kwargs mirror StorageMetadata fields; bundling them into a dataclass would duplicate the model itself without saving anything.
        cls,
        *,
        endpoint: str,
        pyholman_version: str,
        run_mode: StorageRunMode,
        run_started_utc: datetime,
        run_completed_utc: datetime,
        most_recent_record_utc: datetime | None,
        record_count: int,
        output_format: OutputFormat,
        compression: ParquetCompression | None,
        filters_hash: str,
    ) -> Self:
        """
        Construct metadata for an incremental-capable endpoint.

        ``run_mode`` reflects whether this run was a full refresh or
        an incremental update — both are valid for incremental-capable
        endpoints; a first-time pull still reports ``INCREMENTAL`` if
        the resource is configured that way.
        ``most_recent_record_utc`` must be non-``None`` whenever
        ``record_count > 0``: incremental-capable endpoints always have
        a record-level anchor when records are present. The factory
        enforces that rule (the base validator does not, because
        snapshot endpoints legitimately have ``None`` with non-zero
        records). For snapshot-only endpoints, use
        :meth:`for_snapshot` instead.

        Args:
            endpoint: Short identifier of the Holman endpoint.
            pyholman_version: Version string captured by
                :func:`pyholman._storage.metadata.version.get_pyholman_version`.
            run_mode: ``FULL_REFRESH`` or ``INCREMENTAL`` per the
                resource's configuration.
            run_started_utc: UTC timestamp when the run began.
            run_completed_utc: UTC timestamp when the run finished.
            most_recent_record_utc: Newest watermark value across
                persisted rows. ``None`` is permitted only when
                ``record_count == 0``.
            record_count: Number of rows in the persisted file.
            output_format: Serialization format of the data file.
            compression: Parquet compression codec (or ``None``).
            filters_hash: SHA-256 hex digest of the filter model.

        Returns:
            A validated :class:`StorageMetadata` instance.

        Raises:
            ValueError: If ``record_count > 0`` and
                ``most_recent_record_utc`` is ``None``.
        """
        if record_count > 0 and most_recent_record_utc is None:
            raise ValueError(
                f'StorageMetadata.for_incremental: record_count is '
                f'{record_count} but most_recent_record_utc is None. '
                f'Incremental-capable endpoints always have a record-level '
                f'anchor when records are present. For snapshot-only '
                f'endpoints, use for_snapshot instead.'
            )
        return cls(
            endpoint=endpoint,
            pyholman_version=pyholman_version,
            run_mode=run_mode,
            run_started_utc=run_started_utc,
            run_completed_utc=run_completed_utc,
            most_recent_record_utc=most_recent_record_utc,
            record_count=record_count,
            output_format=output_format,
            compression=compression,
            filters_hash=filters_hash,
        )

    @classmethod
    def from_json(cls, file_path: Path) -> Self:
        """
        Load a ``StorageMetadata`` from a JSON sidecar file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            A validated ``StorageMetadata`` instance.

        Raises:
            FileNotFoundError: If ``file_path`` does not exist. The
                message includes the path.
            pydantic.ValidationError: If the JSON content does not
                satisfy the model.
        """
        if not file_path.exists():
            raise FileNotFoundError(
                f'StorageMetadata JSON sidecar not found at {file_path}'
            )

        logger.debug('Loading StorageMetadata: %s', file_path)
        json_content: str = file_path.read_text(encoding='utf-8')
        return cls.model_validate_json(json_content)

    def to_json(self, file_path: Path) -> None:
        """
        Write this ``StorageMetadata`` as an atomic, pretty-printed JSON file.

        The output is indented for human readability and terminates with
        a single trailing newline (POSIX convention). The write uses
        :func:`atomicwrites.atomic_write` so a crash mid-write leaves the
        prior sidecar (if any) intact.

        Args:
            file_path: Target path. Parent directory must already exist.

        Returns:
            None.

        Side Effects:
            Creates or atomically replaces ``file_path`` on disk.
        """
        logger.debug('Writing StorageMetadata: %s', file_path)

        json_payload: str = self.model_dump_json(indent=2) + '\n'
        with atomic_write(
            str(file_path),
            mode='w',
            encoding='utf-8',
            overwrite=True,
        ) as text_handle:
            text_handle.write(json_payload)

        logger.info('Wrote StorageMetadata: %s', file_path)
