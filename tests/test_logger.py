# tests/test_logger.py
"""Tests for pyholman._logger."""

import importlib
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import pyholman._logger.setup as _pyholman_logger_setup_module
from pyholman._config import LoggerConfig
from pyholman._logger import setup_logger

__all__: list[str] = []

# Package logger name — must stay in sync with setup.py. Duplicated here
# (not imported) because the production constant is underscore-prefixed;
# importing it would leak a private name across modules.
_PACKAGE_LOGGER_NAME: str = 'pyholman'

# Expected format strings from setup.py. Reproduced for identity checks.
_EXPECTED_LOG_FORMAT: str = '%(asctime)s - %(levelname)-8s - [%(name)s] - %(message)s'
_EXPECTED_DATE_FORMAT: str = '%Y-%m-%d %H:%M:%S'


@pytest.fixture(autouse=True)
def _reset_package_logger() -> Iterator[None]:
    """
    Snapshot and restore the ``pyholman`` logger around every test.

    Python's ``logging`` module uses global singletons keyed by name. Each
    test must start from a known state and leave no residue, or one test
    will see handlers another attached. The snapshot preserves whatever
    the test session started with (usually the import-time NullHandler)
    and puts it back at teardown.
    """
    package_logger: logging.Logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    original_handlers: list[logging.Handler] = list(package_logger.handlers)
    original_level: int = package_logger.level
    original_propagate: bool = package_logger.propagate

    package_logger.handlers.clear()
    package_logger.setLevel(logging.NOTSET)
    package_logger.propagate = True

    try:
        yield
    finally:
        # Close any handlers the test attached so open file descriptors
        # (e.g., FileHandlers pointing into ``tmp_path``) are released
        # before pytest tears ``tmp_path`` down. Without this, a
        # ``ResourceWarning`` / ``PytestUnraisableExceptionWarning``
        # surfaces when the file disappears while the handler still holds
        # it open.
        for handler in package_logger.handlers:
            handler.close()
        package_logger.handlers.clear()
        package_logger.handlers.extend(original_handlers)
        package_logger.setLevel(original_level)
        package_logger.propagate = original_propagate


def _get_package_logger() -> logging.Logger:
    return logging.getLogger(_PACKAGE_LOGGER_NAME)


# =============================================================================
# Console-only configuration
# =============================================================================


class TestConsoleOnly:
    def test_single_stream_handler_targeting_stderr(self) -> None:
        setup_logger(LoggerConfig(console_level=logging.INFO))

        package_logger: logging.Logger = _get_package_logger()
        assert len(package_logger.handlers) == 1

        console_handler: logging.Handler = package_logger.handlers[0]
        assert type(console_handler) is logging.StreamHandler
        assert isinstance(console_handler, logging.StreamHandler)
        assert console_handler.stream is sys.stderr
        assert console_handler.level == logging.INFO

    def test_no_file_handler_when_file_path_is_none(self) -> None:
        setup_logger(LoggerConfig(console_level=logging.INFO))
        handlers: list[logging.Handler] = _get_package_logger().handlers
        assert not any(isinstance(h, logging.FileHandler) for h in handlers)

    def test_propagation_disabled(self) -> None:
        setup_logger(LoggerConfig(console_level=logging.INFO))
        assert _get_package_logger().propagate is False

    def test_package_level_equals_console_level(self) -> None:
        setup_logger(LoggerConfig(console_level=logging.WARNING))
        assert _get_package_logger().level == logging.WARNING


# =============================================================================
# Console + file configuration
# =============================================================================


class TestConsoleAndFile:
    def test_two_handlers_second_is_file_handler(self, tmp_path: Path) -> None:
        log_file: Path = tmp_path / 'pyholman.log'
        setup_logger(
            LoggerConfig(
                console_level=logging.INFO,
                file_path=log_file,
                file_level=logging.DEBUG,
            )
        )

        handlers: list[logging.Handler] = _get_package_logger().handlers
        assert len(handlers) == 2

        # logging.FileHandler is a subclass of StreamHandler, so the
        # stream-handler assertion would pass for both; filter by exact
        # type to isolate the file handler.
        file_handlers: list[logging.FileHandler] = [
            h for h in handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        file_handler: logging.FileHandler = file_handlers[0]
        assert file_handler.baseFilename == str(log_file.resolve())
        assert file_handler.mode == 'a'
        assert file_handler.encoding == 'utf-8'
        assert file_handler.level == logging.DEBUG

    def test_package_level_is_minimum_of_handler_levels(
        self,
        tmp_path: Path,
    ) -> None:
        setup_logger(
            LoggerConfig(
                console_level=logging.WARNING,
                file_path=tmp_path / 'x.log',
                file_level=logging.DEBUG,
            )
        )
        assert _get_package_logger().level == logging.DEBUG

    def test_package_level_when_console_is_lower(self, tmp_path: Path) -> None:
        # Inverse of the common case — console at DEBUG, file at WARNING.
        setup_logger(
            LoggerConfig(
                console_level=logging.DEBUG,
                file_path=tmp_path / 'x.log',
                file_level=logging.WARNING,
            )
        )
        assert _get_package_logger().level == logging.DEBUG

    def test_parent_directory_created_when_missing(
        self,
        tmp_path: Path,
    ) -> None:
        nested_log: Path = tmp_path / 'nested' / 'sub' / 'pyholman.log'
        assert not nested_log.parent.exists()

        setup_logger(
            LoggerConfig(
                console_level=logging.INFO,
                file_path=nested_log,
                file_level=logging.DEBUG,
            )
        )

        assert nested_log.parent.is_dir()


# =============================================================================
# Idempotency and return type
# =============================================================================


class TestIdempotencyAndReturn:
    def test_return_value_is_none(self) -> None:
        assert setup_logger(LoggerConfig(console_level=logging.INFO)) is None

    def test_second_call_replaces_first(self, tmp_path: Path) -> None:
        setup_logger(LoggerConfig(console_level=logging.INFO))
        assert len(_get_package_logger().handlers) == 1

        setup_logger(
            LoggerConfig(
                console_level=logging.ERROR,
                file_path=tmp_path / 'second.log',
                file_level=logging.WARNING,
            )
        )

        handlers: list[logging.Handler] = _get_package_logger().handlers
        assert len(handlers) == 2

        # Second call's levels must be reflected on the handlers.
        console_handlers: list[logging.StreamHandler[object]] = [
            h for h in handlers if type(h) is logging.StreamHandler
        ]
        file_handlers: list[logging.FileHandler] = [
            h for h in handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert len(file_handlers) == 1
        assert console_handlers[0].level == logging.ERROR
        assert file_handlers[0].level == logging.WARNING

    def test_idempotency_preserves_handler_count_on_repeated_calls(self) -> None:
        for _ in range(5):
            setup_logger(LoggerConfig(console_level=logging.INFO))
        assert len(_get_package_logger().handlers) == 1


# =============================================================================
# Formatter and completion log
# =============================================================================


class TestFormatter:
    def test_every_handler_uses_expected_format_and_datefmt(
        self,
        tmp_path: Path,
    ) -> None:
        setup_logger(
            LoggerConfig(
                console_level=logging.INFO,
                file_path=tmp_path / 'x.log',
                file_level=logging.DEBUG,
            )
        )

        for handler in _get_package_logger().handlers:
            formatter: logging.Formatter | None = handler.formatter
            assert formatter is not None
            # Pydantic's Formatter stores the format as _fmt / _style._fmt;
            # both are stable-enough CPython internals for a test assertion.
            assert formatter._fmt == _EXPECTED_LOG_FORMAT
            assert formatter.datefmt == _EXPECTED_DATE_FORMAT


class TestCompletionLog:
    """
    setup_logger sets ``propagate=False`` on the package logger, so
    caplog (which attaches to the root logger) does not observe records
    emitted from within pyholman. The just-installed ``StreamHandler``
    writes to ``sys.stderr`` — pytest's ``capsys`` captures that stream
    and lets us assert on the formatted output.
    """

    def test_info_record_emitted_for_console_only(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        setup_logger(LoggerConfig(console_level=logging.INFO))

        stderr_output: str = capsys.readouterr().err
        assert 'Logging configured: console_level=INFO' in stderr_output
        # The completion log must not mention a file when file logging is off.
        assert 'file=' not in stderr_output

    def test_info_record_includes_file_path_when_file_enabled(
        self,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        log_file: Path = tmp_path / 'pyholman.log'

        setup_logger(
            LoggerConfig(
                console_level=logging.INFO,
                file_path=log_file,
                file_level=logging.DEBUG,
            )
        )

        # Console handler at INFO level shows the completion log.
        stderr_output: str = capsys.readouterr().err
        assert 'Logging configured: console_level=INFO' in stderr_output
        assert f'file={log_file}' in stderr_output

        # The file handler must record the same completion log — verifying
        # both handlers are wired up and the file handler's file is flushable.
        for handler in _get_package_logger().handlers:
            handler.flush()
        file_contents: str = log_file.read_text(encoding='utf-8')
        assert 'Logging configured: console_level=INFO' in file_contents
        assert f'file={log_file}' in file_contents


# =============================================================================
# Inheritance
# =============================================================================


class TestInheritance:
    """
    Submodule loggers (``pyholman.<anything>``) propagate records up to
    the ``pyholman`` package logger, which carries the handlers installed
    by ``setup_logger``. The record is then filtered by the package
    logger's level (min of console/file levels) and its handler levels.
    We verify the effective floor by reading the stderr stream the
    console handler targets.
    """

    @pytest.mark.parametrize(
        ('configured_level', 'emitted_level', 'should_capture'),
        [
            (logging.DEBUG, logging.DEBUG, True),
            (logging.DEBUG, logging.INFO, True),
            (logging.INFO, logging.DEBUG, False),
            (logging.INFO, logging.INFO, True),
            (logging.WARNING, logging.INFO, False),
            (logging.WARNING, logging.WARNING, True),
            (logging.WARNING, logging.ERROR, True),
        ],
    )
    def test_submodule_logger_respects_package_level(
        self,
        capsys: pytest.CaptureFixture[str],
        configured_level: int,
        emitted_level: int,
        should_capture: bool,
    ) -> None:
        setup_logger(LoggerConfig(console_level=configured_level))
        # Drop the completion log emitted inside setup_logger so the
        # assertion window below sees only the submodule's emission.
        capsys.readouterr()

        marker_message: str = f'inherit-marker-{emitted_level}'
        submodule_logger: logging.Logger = logging.getLogger('pyholman.some_submodule')
        submodule_logger.log(emitted_level, marker_message)

        stderr_output: str = capsys.readouterr().err
        if should_capture:
            assert marker_message in stderr_output
        else:
            assert marker_message not in stderr_output


# =============================================================================
# NullHandler registration at import time
# =============================================================================


class TestNullHandlerRegistration:
    def test_fresh_reload_attaches_single_null_handler(self) -> None:
        package_logger: logging.Logger = _get_package_logger()
        package_logger.handlers.clear()

        importlib.reload(_pyholman_logger_setup_module)

        null_handlers: list[logging.Handler] = [
            h for h in package_logger.handlers if isinstance(h, logging.NullHandler)
        ]
        assert len(package_logger.handlers) == 1
        assert len(null_handlers) == 1

    def test_reload_does_not_stack_null_handlers_when_real_handlers_present(
        self,
    ) -> None:
        package_logger: logging.Logger = _get_package_logger()
        package_logger.handlers.clear()

        # Simulate the post-setup_logger state: a real handler already
        # installed. The reload guard must detect this and refuse to add
        # another NullHandler that would quietly suppress nothing.
        real_handler: logging.Handler = logging.StreamHandler(sys.stderr)
        package_logger.addHandler(real_handler)
        handler_count_before_reload: int = len(package_logger.handlers)

        importlib.reload(_pyholman_logger_setup_module)

        assert len(package_logger.handlers) == handler_count_before_reload
        null_handlers: list[logging.Handler] = [
            h for h in package_logger.handlers if isinstance(h, logging.NullHandler)
        ]
        assert len(null_handlers) == 0
