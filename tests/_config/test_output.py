# tests/_config/test_output.py
"""Tests for OutputConfig and its enums."""

import pytest
from pydantic import ValidationError

from pyholman._config import OutputConfig, OutputFormat, ParquetCompression

__all__: list[str] = []


class TestOutputConfigFormatAndCompression:
    def test_default_format_is_parquet(self) -> None:
        config: OutputConfig = OutputConfig()
        assert config.format is OutputFormat.PARQUET

    def test_parquet_defaults_compression_to_snappy(self) -> None:
        config: OutputConfig = OutputConfig(format='parquet')
        assert config.compression is ParquetCompression.SNAPPY

    def test_explicit_parquet_compression_preserved(self) -> None:
        config: OutputConfig = OutputConfig(
            format='parquet',
            compression='zstd',
        )
        assert config.compression is ParquetCompression.ZSTD

    def test_explicit_null_compression_preserved_for_parquet(self) -> None:
        # A user who wants uncompressed Parquet supplies ``compression: null``
        # explicitly; the default-injection logic only fires when the key is
        # entirely absent.
        config: OutputConfig = OutputConfig(
            format='parquet',
            compression=None,
        )
        assert config.compression is None

    def test_csv_with_no_compression(self) -> None:
        config: OutputConfig = OutputConfig(format='csv')
        assert config.format is OutputFormat.CSV
        assert config.compression is None

    @pytest.mark.parametrize(
        'compression_value',
        ['snappy', 'gzip', 'brotli', 'zstd', 'lz4'],
    )
    def test_csv_with_any_compression_rejected(
        self,
        compression_value: str,
    ) -> None:
        with pytest.raises(ValidationError, match="omitted when format is 'csv'"):
            OutputConfig(
                format='csv',
                compression=compression_value,
            )

    @pytest.mark.parametrize(
        'bad_format',
        ['tsv', 'JSON', 'parquett'],
    )
    def test_invalid_format_rejected(
        self,
        bad_format: str,
    ) -> None:
        with pytest.raises(ValidationError):
            OutputConfig(format=bad_format)

    def test_invalid_compression_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputConfig(
                format='parquet',
                compression='bz2',
            )


class TestOutputConfigImmutability:
    def test_is_frozen(self) -> None:
        config: OutputConfig = OutputConfig()
        with pytest.raises(ValidationError):
            config.format = OutputFormat.CSV  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            OutputConfig(
                oops='typo',  # type: ignore[call-arg]
            )

    def test_directory_key_rejected(self) -> None:
        # Regression guard: ``directory`` used to live here; the schema
        # change promoted it to ``UserConfig.working_directory``. Passing
        # ``directory=`` to ``OutputConfig`` must fail via extra='forbid'
        # so stale YAML and stale call sites surface loudly.
        with pytest.raises(ValidationError, match='directory'):
            OutputConfig(directory='/tmp/whatever')  # type: ignore[call-arg]
