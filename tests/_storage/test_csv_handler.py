# tests/_storage/test_csv_handler.py
"""Tests for the atomic CSV reader/writer."""

import os
import warnings
from pathlib import Path
from typing import Any

import atomicwrites
import pandas as pd
import pytest

from pyholman._storage.csv_handler import _read_csv_file, _write_csv_file

__all__: list[str] = []


def _make_csv_source_frame() -> pd.DataFrame:
    """A small frame of mixed scalars suitable for CSV round-trip checks."""
    return pd.DataFrame(
        {
            'id': [1, 2, 3],
            'name': ['alpha', 'beta', 'gamma'],
            'score': [1.5, 2.5, 3.5],
            'flag': [True, False, True],
        }
    )


class TestRoundTrip:
    def test_values_round_trip_even_though_dtypes_are_lossy(
        self,
        tmp_path: Path,
    ) -> None:
        # CSV is lossy for dtypes. We assert values match (via equality on
        # the rendered representations) and explicitly document what
        # pandas infers on the read side so a future change is noticed.
        source_frame: pd.DataFrame = _make_csv_source_frame()
        target_path: Path = tmp_path / 'roundtrip.csv'

        _write_csv_file(dataframe=source_frame, file_path=target_path)
        restored_frame: pd.DataFrame = _read_csv_file(target_path)

        assert list(restored_frame.columns) == list(source_frame.columns)
        assert len(restored_frame) == len(source_frame)
        # Values equal column by column after a string-level comparison —
        # this bypasses dtype differences (int vs Int64, bool vs BoolType).
        for column_name in source_frame.columns:
            assert (
                restored_frame[column_name].astype(str).tolist()
                == source_frame[column_name].astype(str).tolist()
            )

        # Document the dtypes pandas.read_csv infers for this fixture so
        # silent behavior changes are surfaced as test failures.
        inferred_dtypes: dict[str, str] = {
            name: str(dtype) for name, dtype in restored_frame.dtypes.items()
        }
        assert inferred_dtypes == {
            'id': 'int64',
            'name': 'str',
            'score': 'float64',
            'flag': 'bool',
        }


class TestNoDtypeWarning:
    """
    Regression for ``DtypeWarning: Columns (...) have mixed types``
    observed against a real 10,992-row maintenance-PO CSV under pandas
    2.x. Pandas' default chunked inference (~262144 bytes per chunk)
    cannot resolve a single dtype for a column whose value-shape
    changes across a chunk boundary — common for client-defined fields
    that are typed ``string`` upstream but happen to contain
    numeric-looking values in some rows and not others. The fix is
    ``low_memory=False`` on ``pd.read_csv``, which forces a single
    inference pass over the whole file.

    Two complementary tests:
        - A behavioral test that reads a large multi-chunk fixture and
          asserts no ``DtypeWarning`` was emitted. This catches the
          regression directly on pandas versions that still emit the
          warning (2.x).
        - A pin on the call shape itself, asserting
          ``low_memory=False`` reaches ``pd.read_csv``. This catches
          the regression on any pandas version, including pandas 3.x
          where the warning behavior has changed and the behavioral
          test would pass vacuously.
    """

    def test_reader_does_not_emit_dtype_warning_on_mixed_type_column(
        self,
        tmp_path: Path,
    ) -> None:
        # Build a frame large enough to span at least one internal
        # chunk boundary, with a column whose value-shape alternates
        # so chunked inference would land on different dtypes across
        # chunks. Padding columns inflate per-row width so a few
        # thousand rows comfortably exceed the chunk size.
        row_count: int = 5000
        padding_value: str = 'x' * 64
        mixed_values: list[str] = [str(index) for index in range(row_count // 2)] + [
            f'label-{index}' for index in range(row_count // 2)
        ]
        source_frame: pd.DataFrame = pd.DataFrame(
            {
                'id': list(range(row_count)),
                'mixed_typed': mixed_values,
                'pad_a': [padding_value] * row_count,
                'pad_b': [padding_value] * row_count,
                'pad_c': [padding_value] * row_count,
            }
        )

        target_path: Path = tmp_path / 'mixed_types.csv'
        _write_csv_file(dataframe=source_frame, file_path=target_path)

        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter('always')
            restored_frame: pd.DataFrame = _read_csv_file(target_path)

        dtype_warnings: list[warnings.WarningMessage] = [
            warning
            for warning in captured_warnings
            if issubclass(warning.category, pd.errors.DtypeWarning)
        ]
        assert dtype_warnings == [], (
            f'expected no DtypeWarning, got: '
            f'{[str(warning.message) for warning in dtype_warnings]}'
        )
        assert len(restored_frame) == row_count

    def test_low_memory_false_is_passed_to_read_csv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Cross-pandas-version pin: regardless of whether the running
        # pandas version still emits ``DtypeWarning``, the read must
        # call ``pd.read_csv`` with ``low_memory=False``. Removing the
        # kwarg is a regression even on pandas versions that have
        # silenced the warning by other means, because chunked
        # inference can still produce a different inferred dtype than
        # single-pass inference for the same input.
        from pyholman._storage import csv_handler  # noqa: PLC0415

        target_path: Path = tmp_path / 'pin.csv'
        _write_csv_file(dataframe=_make_csv_source_frame(), file_path=target_path)

        captured_kwargs: dict[str, Any] = {}
        real_read_csv = csv_handler.pd.read_csv

        def _capturing_read_csv(*args: Any, **kwargs: Any) -> pd.DataFrame:
            captured_kwargs.update(kwargs)
            return real_read_csv(*args, **kwargs)

        monkeypatch.setattr(csv_handler.pd, 'read_csv', _capturing_read_csv)

        _read_csv_file(target_path)

        assert captured_kwargs.get('low_memory') is False, (
            f'expected low_memory=False to be passed to pd.read_csv, '
            f'got kwargs: {captured_kwargs!r}'
        )


class TestLineEndings:
    def test_writer_does_not_emit_double_carriage_returns_on_windows(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Regression for Excel / Power BI seeing one blank row between
        # every real row on Windows. The bug was a text-mode write
        # without ``newline=''``: pandas emits ``os.linesep`` (``\r\n``
        # on Windows) per row, and Python's text-mode translation then
        # turns each ``\n`` into ``\r\n``, so the file lands as
        # ``\r\r\n``-separated. ``pandas.read_csv`` tolerates this,
        # which is exactly what masked the bug — so we hit the bytes
        # directly rather than going through any pandas reader.
        #
        # The bug only manifests on Windows. To make the regression
        # deterministic on every platform, we simulate the two
        # Windows-specific behaviors that combine to produce it:
        #   1. ``os.linesep`` is ``'\r\n'`` (drives pandas' default
        #      ``lineterminator``, read at ``to_csv`` call time).
        #   2. Text-mode ``open`` with ``newline=None`` translates
        #      ``\n`` to ``os.linesep``. Linux Python's text mode never
        #      translates regardless of ``os.linesep``, so we wrap
        #      ``atomicwrites.io.open`` to inject ``newline='\r\n'``
        #      whenever the caller did not specify one.
        # Together these reproduce the Windows write path exactly. The
        # fix is for the writer to pass ``newline=''`` explicitly so the
        # injection is suppressed and no translation occurs.
        monkeypatch.setattr(os, 'linesep', '\r\n')

        real_get_fileobject = atomicwrites.AtomicWriter.get_fileobject

        def get_fileobject_with_windows_translation(
            self: atomicwrites.AtomicWriter,
            **kwargs: Any,
        ) -> Any:
            if 'b' not in self._mode and 'newline' not in kwargs:
                kwargs['newline'] = '\r\n'
            return real_get_fileobject(self, **kwargs)

        monkeypatch.setattr(
            atomicwrites.AtomicWriter,
            'get_fileobject',
            get_fileobject_with_windows_translation,
        )

        target_path: Path = tmp_path / 'line_endings.csv'
        _write_csv_file(dataframe=_make_csv_source_frame(), file_path=target_path)

        raw_bytes: bytes = target_path.read_bytes()
        assert b'\r\r' not in raw_bytes
        # The intended terminator is ``\r\n`` on Windows.
        assert b'\r\n' in raw_bytes


class TestEmptyDataFrame:
    def test_empty_write_raises_without_touching_disk(
        self,
        tmp_path: Path,
    ) -> None:
        target_path: Path = tmp_path / 'empty.csv'
        empty_frame: pd.DataFrame = pd.DataFrame({'id': []})

        with pytest.raises(ValueError, match=str(target_path)):
            _write_csv_file(dataframe=empty_frame, file_path=target_path)

        assert not target_path.exists()


class TestAtomicity:
    def test_mid_write_crash_leaves_prior_file_intact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target_path: Path = tmp_path / 'atomic.csv'

        first_frame: pd.DataFrame = _make_csv_source_frame()
        _write_csv_file(dataframe=first_frame, file_path=target_path)
        prior_bytes: bytes = target_path.read_bytes()

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_csv', _explode)

        second_frame: pd.DataFrame = _make_csv_source_frame()
        with pytest.raises(RuntimeError, match='simulated crash'):
            _write_csv_file(dataframe=second_frame, file_path=target_path)

        assert target_path.read_bytes() == prior_bytes

    def test_mid_write_crash_on_fresh_path_leaves_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target_path: Path = tmp_path / 'fresh.csv'

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated crash mid-write')

        monkeypatch.setattr(pd.DataFrame, 'to_csv', _explode)

        source_frame: pd.DataFrame = _make_csv_source_frame()
        with pytest.raises(RuntimeError, match='simulated crash'):
            _write_csv_file(dataframe=source_frame, file_path=target_path)

        assert not target_path.exists()
