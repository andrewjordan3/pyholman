# src/pyholman/_logger/setup.py
"""
Logging configuration for the pyholman package.

Provides centralized logging setup so every module that calls
``logging.getLogger(__name__)`` inherits the same level, format, and
handler configuration. Users drive the setup from a validated
``LoggerConfig`` — no ad-hoc level parsing or path expansion happens
here; that is the configuration layer's job.

Library convention:
    At import time this module attaches a ``NullHandler`` to the
    ``pyholman`` logger. That guarantees a silent no-op if a downstream
    application never calls ``setup_logger`` — the stdlib emits a
    "no handlers could be found" warning otherwise. The guard below
    ensures a second ``NullHandler`` is not added when the module is
    reloaded after ``setup_logger`` has already attached real handlers.
"""

import logging
import sys
from typing import Final, TextIO

from pyholman._config import LoggerConfig
from pyholman._core.constants import PACKAGE_NAME

__all__: list[str] = ['setup_logger']


# Shared format and date-format for every handler this module attaches.
# Extracted as module-level constants so tests can assert against them by
# identity rather than re-typing the literals.
_LOG_FORMAT: Final[str] = '%(asctime)s - %(levelname)-8s - [%(name)s] - %(message)s'
_DATE_FORMAT: Final[str] = '%Y-%m-%d %H:%M:%S'


def setup_logger(config: LoggerConfig) -> None:
    """
    Configure the pyholman package logger from a ``LoggerConfig``.

    Clears any handlers already attached to the ``pyholman`` logger,
    installs a console handler (always) and an optional file handler,
    and sets the package logger's level so that neither handler is
    starved by an ancestor filter. All module loggers created with
    ``logging.getLogger(__name__)`` inside pyholman inherit the result
    automatically.

    The function is idempotent: calling it twice produces the same handler
    count as one call. The second call's ``LoggerConfig`` fully supersedes
    the first.

    Args:
        config: Validated ``LoggerConfig`` object.
            - ``console_level``: minimum level for stderr output (required).
            - ``file_path``: if set, enables file logging at
              ``file_level`` (guaranteed non-None by the config validator
              whenever ``file_path`` is set).

    Returns:
        None. Matches the stdlib convention (``logging.basicConfig``,
        ``logging.config.dictConfig``, ``logging.config.fileConfig`` all
        return None). Module loggers inherit the configuration
        automatically, so no handle is useful.

    Side Effects:
        - Replaces the ``pyholman`` logger's handlers.
        - Sets ``pyholman`` logger's level to
          ``min(console_level, file_level)`` so no record is filtered at
          the logger before reaching its handlers.
        - Sets ``pyholman.propagate = False`` so a hosting application
          that configures the root logger does not produce duplicate
          output.
        - Creates the parent directory of ``file_path`` if file logging
          is enabled and the directory does not already exist.
        - Emits a single INFO-level log record confirming the
          configuration, using the just-installed handlers.

    Example:
        >>> import logging
        >>> from pathlib import Path
        >>> from pyholman._config import LoggerConfig
        >>> from pyholman._logger import setup_logger
        >>> setup_logger(
        ...     LoggerConfig(
        ...         console_level=logging.INFO,
        ...         file_path=Path('logs/pyholman.log'),
        ...         file_level=logging.DEBUG,
        ...     )
        ... )
    """
    package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)

    # Clear existing handlers to make the call idempotent and to let a
    # caller reconfigure at runtime without accumulating duplicates.
    package_logger.handlers.clear()

    # A hosting application (e.g., a Jupyter runner) may configure the
    # root logger; disabling propagation here prevents every pyholman
    # record from being emitted twice.
    package_logger.propagate = False

    log_formatter: logging.Formatter = logging.Formatter(
        fmt=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )

    console_handler: logging.StreamHandler[TextIO] = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(config.console_level)
    package_logger.addHandler(console_handler)

    if config.file_path is not None:
        # The LoggerConfig validator guarantees file_level is set whenever
        # file_path is set (defaults to DEBUG when the user omits it); the
        # assert narrows the type for static analyzers and fails loudly if
        # the invariant ever breaks.
        assert config.file_level is not None
        config.file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler: logging.FileHandler = logging.FileHandler(
            filename=config.file_path,
            mode='a',
            encoding='utf-8',
        )
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(config.file_level)
        package_logger.addHandler(file_handler)

    # Set the package logger's own level to the minimum of the handler
    # levels so the logger does not filter records before they reach any
    # handler. When only the console is configured, file_level is None
    # and console_level is the sole floor.
    effective_level: int = (
        config.console_level
        if config.file_level is None
        else min(config.console_level, config.file_level)
    )
    package_logger.setLevel(effective_level)

    package_logger.info(
        'Logging configured: console_level=%s%s',
        logging.getLevelName(config.console_level),
        f', file={config.file_path}' if config.file_path is not None else '',
    )


# =============================================================================
# Library NullHandler registration (import-time side effect)
# =============================================================================
# Python logging HOWTO → "Configuring Logging for a Library": attach a
# NullHandler so that importing pyholman without calling setup_logger does
# not emit the stdlib "no handlers could be found" warning. The guard below
# keeps a reload safe: if real handlers have already been attached (e.g.,
# after setup_logger ran), we do not stack another NullHandler on top.
_package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
if not _package_logger.handlers:
    _package_logger.addHandler(logging.NullHandler())
