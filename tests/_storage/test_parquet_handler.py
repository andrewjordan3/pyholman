# tests/_storage/test_parquet_handler.py
"""Tests for the atomic Parquet reader/writer."""

from pathlib import Path

import pandas as pd
import pytest

from pyholman._config import ParquetCompression
from pyholman._storage.parquet_handler import _read_parquet_file, _write_parquet_file

__all__: list[str] = []


# The full set of pandas nullable dtypes the storage layer promises to
# round-trip. Listed once here so every round-trip test uses the same
# fixture rather than drifting into inconsistent expectations.
_SUPPORTED_DTYPES: list[str] = [
    'Int64',
    'Float64',
    'string',
    'boolean',
    'datetime64[us, UTC]',
]


def _make_all_dtypes_frame() -> pd.DataFrame:
    """Build a three-row DataFrame exercising every supported dtype."""
    return pd.DataFrame(
        {
            'int_col': pd.array([1, 2, 3], dtype='Int64'),
            'float_col': pd.array([1.5, 2.5, 3.5], dtype='Float64'),
            'string_col': pd.array(['alpha', 'beta', 'gamma'], dtype='string'),
            'bool_col': pd.array([True, False, True], dtype='boolean'),
            'datetime_col': pd.to_datetime(
                ['2024-01-01', '2024-01-02', '2024-01-03'],
                utc=True,
            ).astype('datetime64[us, UTC]'),
        }
    )


def _make_frame_with_nulls() -> pd.DataFrame:
    """Build a frame with exactly one NA in every supported dtype."""
    return pd.DataFrame(
        {
            'int_col': pd.array([1, pd.NA, 3], dtype='Int64'),
            'float_col': pd.array([1.5, pd.NA, 3.5], dtype='Float64'),
            'string_col': pd.array(['alpha', pd.NA, 'gamma'], dtype='string'),
            'bool_col': pd.array([True, pd.NA, False], dtype='boolean'),
            'datetime_col': pd.to_datetime(
                ['2024-01-01', None, '2024-01-03'],
                utc=True,
            ).astype('datetime64[us, UTC]'),
        }
    )


class TestRoundTrip:
    def test_all_supported_dtypes_round_trip(self, tmp_path: Path) -> None:
        source_frame: pd.DataFrame = _make_all_dtypes_frame()
        target_path: Path = tmp_path / 'all.parquet'

        _write_parquet_file(
            dataframe=source_frame,
            file_path=target_path,
            compression=ParquetCompression.SNAPPY,
        )
        restored_frame: pd.DataFrame = _read_parquet_file(target_path)

        pd.testing.assert_frame_equal(restored_frame, source_frame)
        # Extra belt-and-suspenders: each dtype matches by name.
        assert [str(dtype) for dtype in restored_frame.dtypes] == _SUPPORTED_DTYPES

    def test_nulls_round_trip(self, tmp_path: Path) -> None:
        source_frame: pd.DataFrame = _make_frame_with_nulls()
        target_path: Path = tmp_path / 'nulls.parquet'

        _write_parquet_file(
            dataframe=source_frame,
            file_path=target_path,
            compression=ParquetCompression.SNAPPY,
        )
        restored_frame: pd.DataFrame = _read_parquet_file(target_path)

        pd.testing.assert_frame_equal(restored_frame, source_frame)

    @pytest.mark.parametrize(
        'compression',
        [
            ParquetCompression.SNAPPY,
            ParquetCompression.GZIP,
            ParquetCompression.BROTLI,
            ParquetCompression.ZSTD,
            ParquetCompression.LZ4,
            None,
        ],
    )
    def test_every_compression_round_trips(
        self,
        tmp_path: Path,
        compression: ParquetCompression | None,
    ) -> None:
        source_frame: pd.DataFrame = _make_all_dtypes_frame()
        label: str = compression.value if compression is not None else 'none'
        target_path: Path = tmp_path / f'{label}.parquet'

        _write_parquet_file(
            dataframe=source_frame,
            file_path=target_path,
            compression=compression,
        )
        restored_frame: pd.DataFrame = _read_parquet_file(target_path)

        pd.testing.assert_frame_equal(restored_frame, source_frame)


class TestTimestampPrecision:
    def test_ns_precision_with_zero_subus_coerces_cleanly(
        self,
        tmp_path: Path,
    ) -> None:
        # datetime64[ns, UTC] values whose nanosecond component is zero
        # should coerce to microseconds without error. Pandas 3 defaults
        # new-from-string datetimes to microsecond precision, so we
        # explicitly cast to nanoseconds to exercise the code path.
        ns_datetime_series: pd.Series = pd.Series(
            pd.to_datetime(
                ['2024-01-01 12:34:56.789000', '2024-02-01 00:00:00'],
                utc=True,
                format='ISO8601',
            )
        ).astype('datetime64[ns, UTC]')
        assert str(ns_datetime_series.dtype) == 'datetime64[ns, UTC]'

        source_frame: pd.DataFrame = pd.DataFrame({'ts': ns_datetime_series})
        target_path: Path = tmp_path / 'ns_zero.parquet'

        _write_parquet_file(
            dataframe=source_frame,
            file_path=target_path,
            compression=None,
        )
        restored_frame: pd.DataFrame = _read_parquet_file(target_path)

        # The restored frame comes back at microsecond precision.
        assert str(restored_frame['ts'].dtype) == 'datetime64[us, UTC]'
        # Values match once we also coerce the source to microseconds for
        # a fair comparison.
        pd.testing.assert_series_equal(
            restored_frame['ts'],
            source_frame['ts'].astype('datetime64[us, UTC]'),
        )

    def test_real_nanoseconds_raise(self, tmp_path: Path) -> None:
        ns_datetime_series: pd.Series = pd.to_datetime(
            ['2024-01-01 12:34:56.789000001'],
            utc=True,
            format='ISO8601',
        ).astype('datetime64[ns, UTC]')
        source_frame: pd.DataFrame = pd.DataFrame({'ts': ns_datetime_series})
        target_path: Path = tmp_path / 'real_ns.parquet'

        with pytest.raises(ValueError, match='timestamp'):
            _write_parquet_file(
                dataframe=source_frame,
                file_path=target_path,
                compression=None,
            )


class TestEmptyDataFrame:
    def test_empty_write_raises_without_touching_disk(
        self,
        tmp_path: Path,
    ) -> None:
        target_path: Path = tmp_path / 'empty.parquet'
        empty_frame: pd.DataFrame = pd.DataFrame(
            {'int_col': pd.array([], dtype='Int64')}
        )

        with pytest.raises(ValueError, match=str(target_path)):
            _write_parquet_file(
                dataframe=empty_frame,
                file_path=target_path,
                compression=ParquetCompression.SNAPPY,
            )

        assert not target_path.exists()


class TestAtomicity:
    def test_mid_write_crash_leaves_prior_file_intact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target_path: Path = tmp_path / 'atomic.parquet'

        first_frame: pd.DataFrame = _make_all_dtypes_frame()
        _write_parquet_file(
            dataframe=first_frame,
            file_path=target_path,
            compression=ParquetCompression.SNAPPY,
        )
        prior_bytes: bytes = target_path.read_bytes()

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_parquet', _explode)

        second_frame: pd.DataFrame = _make_all_dtypes_frame()
        with pytest.raises(RuntimeError, match='simulated crash'):
            _write_parquet_file(
                dataframe=second_frame,
                file_path=target_path,
                compression=ParquetCompression.SNAPPY,
            )

        # Prior bytes are still exactly what we wrote first.
        assert target_path.read_bytes() == prior_bytes

    def test_mid_write_crash_on_fresh_path_leaves_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target_path: Path = tmp_path / 'fresh.parquet'

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_parquet', _explode)

        source_frame: pd.DataFrame = _make_all_dtypes_frame()
        with pytest.raises(RuntimeError, match='simulated crash'):
            _write_parquet_file(
                dataframe=source_frame,
                file_path=target_path,
                compression=ParquetCompression.SNAPPY,
            )

        assert not target_path.exists()
