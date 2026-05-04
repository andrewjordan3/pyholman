# tests/_config/test_logger.py
"""Tests for LoggerConfig."""

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from pyholman._config import LoggerConfig

__all__: list[str] = []


class TestLoggerConfigConsoleLevel:
    def test_default_console_level_is_warning(self) -> None:
        # Library convention: stay quiet by default. The application
        # opts into INFO/DEBUG when it wants pyholman's progress output.
        config: LoggerConfig = LoggerConfig()
        assert config.console_level == logging.WARNING

    @pytest.mark.parametrize(
        ('raw_level', 'expected_int'),
        [
            ('INFO', logging.INFO),
            ('info', logging.INFO),
            ('Info', logging.INFO),
            ('  INFO  ', logging.INFO),
            ('DEBUG', logging.DEBUG),
            ('WARNING', logging.WARNING),
            ('ERROR', logging.ERROR),
            ('CRITICAL', logging.CRITICAL),
            (logging.INFO, logging.INFO),
            (logging.DEBUG, logging.DEBUG),
        ],
    )
    def test_accepts_valid_levels(
        self,
        raw_level: str | int,
        expected_int: int,
    ) -> None:
        config: LoggerConfig = LoggerConfig(console_level=raw_level)
        assert config.console_level == expected_int

    @pytest.mark.parametrize(
        'bad_level',
        ['LOUD', 'notice', '', '   '],
    )
    def test_rejects_unknown_string_levels(self, bad_level: str) -> None:
        with pytest.raises(ValidationError, match='log level'):
            LoggerConfig(console_level=bad_level)

    @pytest.mark.parametrize('bad_int', [0, 1, -1, 99, 100])
    def test_rejects_non_standard_integers(self, bad_int: int) -> None:
        with pytest.raises(ValidationError, match='standard log level'):
            LoggerConfig(console_level=bad_int)

    def test_rejects_bool(self) -> None:
        with pytest.raises(ValidationError, match='bool'):
            LoggerConfig(console_level=True)  # type: ignore[arg-type]


class TestLoggerConfigFileOutput:
    def test_default_construction_yields_no_file_output(self) -> None:
        config: LoggerConfig = LoggerConfig()
        assert config.file_path is None
        assert config.file_level is None

    def test_file_path_defaults_to_none(self) -> None:
        config: LoggerConfig = LoggerConfig(console_level='INFO')
        assert config.file_path is None
        assert config.file_level is None

    def test_explicit_null_file_path_allowed(self) -> None:
        config: LoggerConfig = LoggerConfig(
            console_level='INFO',
            file_path=None,
        )
        assert config.file_path is None

    def test_file_path_expanded_and_absolute(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('HOME', str(tmp_path))
        config: LoggerConfig = LoggerConfig(
            console_level='INFO',
            file_path='~/logs/foo.log',
        )
        assert config.file_path is not None
        assert config.file_path.is_absolute()
        assert str(tmp_path) in str(config.file_path)

    def test_file_level_defaults_to_debug_when_path_set(
        self,
        tmp_path: Path,
    ) -> None:
        config: LoggerConfig = LoggerConfig(
            console_level='INFO',
            file_path=tmp_path / 'x.log',
        )
        assert config.file_level == logging.DEBUG

    def test_explicit_file_level_respected(self, tmp_path: Path) -> None:
        config: LoggerConfig = LoggerConfig(
            console_level='INFO',
            file_path=tmp_path / 'x.log',
            file_level='WARNING',
        )
        assert config.file_level == logging.WARNING

    def test_explicit_null_file_level_preserved(self, tmp_path: Path) -> None:
        # Explicit None (distinct from omission) must be preserved —
        # the default-injection logic only fires when the key is absent.
        config: LoggerConfig = LoggerConfig(
            console_level='INFO',
            file_path=tmp_path / 'x.log',
            file_level=None,
        )
        assert config.file_level is None

    def test_invalid_file_path_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoggerConfig(
                console_level='INFO',
                file_path=12345,  # type: ignore[arg-type]
            )


class TestLoggerConfigImmutability:
    def test_is_frozen(self) -> None:
        config: LoggerConfig = LoggerConfig()
        with pytest.raises(ValidationError):
            config.console_level = logging.DEBUG  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            LoggerConfig(
                oops='typo',  # type: ignore[call-arg]
            )
