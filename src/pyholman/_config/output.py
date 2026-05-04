# src/pyholman/_config/output.py
"""Output serialization section of the user configuration."""

from enum import StrEnum
from typing import Any

from pydantic import model_validator

from pyholman._core import FrozenModel

__all__: list[str] = [
    'OutputConfig',
    'OutputFormat',
    'ParquetCompression',
]


class OutputFormat(StrEnum):
    """
    Serialization format for pyholman data outputs.

    Members:
        PARQUET: Columnar, compressed, preserves pandas dtypes. Preferred
            for any output that will be re-read programmatically.
        CSV: Plain text, portable, larger files, does not preserve dtypes.
            Useful for handoff to tools that do not read Parquet.
    """

    PARQUET = 'parquet'
    CSV = 'csv'


class ParquetCompression(StrEnum):
    """
    Parquet compression codec.

    Values match the codec strings accepted by ``pandas.DataFrame.to_parquet``.
    There is no ``NONE`` member: an uncompressed output is expressed by
    ``compression = None`` (YAML ``null`` or an omitted key), not by a
    sentinel string.
    """

    SNAPPY = 'snappy'
    GZIP = 'gzip'
    BROTLI = 'brotli'
    ZSTD = 'zstd'
    LZ4 = 'lz4'


class OutputConfig(FrozenModel):
    """
    Output serialization configuration — file format and compression codec.

    The directory in which pyholman writes data lives on
    :class:`~pyholman._config.UserConfig.working_directory`, not here; this
    model owns only the serialization policy.

    Behavior:
        - ``format`` defaults to Parquet.
        - ``compression`` defaults to Snappy when ``format`` is Parquet and
          the user did not supply a key. When the user explicitly writes
          ``compression: null``, the null is preserved (uncompressed output).
        - When ``format`` is CSV, ``compression`` must be omitted or
          ``null``; specifying a codec with CSV is a configuration error
          rather than a silent no-op.
    """

    format: OutputFormat = OutputFormat.PARQUET
    compression: ParquetCompression | None = None

    # The Parquet default is applied *before* field validation so that the
    # frozen model never has to be copied during validation. The rule is:
    # if the user did not supply a ``compression`` key at all AND the format
    # is Parquet (default or explicit), fill in Snappy. An explicit null
    # from the user is preserved verbatim — that is how a user asks for
    # uncompressed Parquet.
    @model_validator(mode='before')
    @classmethod
    def _apply_parquet_default_compression(cls, raw_data: Any) -> Any:
        # ``Any`` is accurate here: Pydantic's ``mode='before'`` validators
        # receive arbitrary pre-validation input — most commonly a
        # ``dict[str, Any]`` from YAML, but also an already-constructed
        # model instance or any other type a caller passes to
        # ``model_validate``. ``object`` would forbid the container
        # operations the ``dict`` branch performs.
        if not isinstance(raw_data, dict):
            return raw_data

        typed_data: dict[str, Any] = raw_data

        compression_key_missing: bool = 'compression' not in typed_data
        format_value: Any = typed_data.get('format', OutputFormat.PARQUET)
        # ``Any`` follows the container: ``dict[str, Any]`` values are
        # arbitrary YAML scalars at this point.
        is_parquet_format: bool = format_value == OutputFormat.PARQUET or (
            isinstance(format_value, str) and format_value.lower() == 'parquet'
        )

        if compression_key_missing and is_parquet_format:
            typed_data = {**typed_data, 'compression': ParquetCompression.SNAPPY}

        return typed_data

    @model_validator(mode='after')
    def _reject_compression_with_csv(self) -> 'OutputConfig':
        """CSV output with any compression codec is a configuration error."""
        if self.format is OutputFormat.CSV and self.compression is not None:
            raise ValueError(
                f"compression must be omitted when format is 'csv', "
                f'got {self.compression.value!r}'
            )
        return self
