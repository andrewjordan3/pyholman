# src/pyholman/_pipeline/incremental_state.py
"""
Pipeline-level signal that the on-disk incremental state is corrupted.

The :class:`IncrementalStateCorruptedError` is raised by
:meth:`ResourceProcessor.merge_incremental` when values on disk that
should be parseable as datetimes (the watermark column of a CSV-backed
data file) cannot be parsed. Every value pyholman itself writes is
round-trippable — :class:`pyholman._core.ResponseModel` validates each
watermark as ``datetime | None`` before it ever reaches a DataFrame and
``to_csv`` serializes datetimes as ISO 8601 — so a parse failure means
either a hand-edit of the CSV between runs or file corruption. In
either case the on-disk state can no longer be merged safely.

This is deliberately **not** a :class:`pyholman.HolmanError`. A
``HolmanError`` signals something went wrong with the Holman API or its
transport; corrupted incremental state is entirely pyholman-internal,
and the remediation is a configuration change (re-run with
``incremental: false`` for the affected resource), not a retry.
"""

from pathlib import Path

__all__: list[str] = ['IncrementalStateCorruptedError']


class IncrementalStateCorruptedError(ValueError):
    """
    Raised when an on-disk incremental data file cannot be merged.

    Attributes:
        resource_name: Registered resource name (e.g., ``'vehicles'``)
            whose data file failed to parse.
        file_path: Absolute path to the on-disk data file.
        watermark_column: Name of the column whose values failed to
            parse as datetimes.
    """

    def __init__(
        self,
        resource_name: str,
        file_path: Path,
        watermark_column: str,
    ) -> None:
        self.resource_name: str = resource_name
        self.file_path: Path = file_path
        self.watermark_column: str = watermark_column
        super().__init__(
            f'Watermark column {watermark_column!r} in {file_path} contains '
            f'values that cannot be parsed as datetimes. The on-disk '
            f'incremental state for resource {resource_name!r} is no longer '
            f'trustworthy. Re-run with `incremental: false` for this '
            f'resource to rebuild from a fresh full refresh.'
        )
