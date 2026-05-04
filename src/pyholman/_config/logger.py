# src/pyholman/_config/logger.py
"""Logger section of the user configuration."""

import logging
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator

from pyholman._core import FrozenModel

__all__: list[str] = ['LoggerConfig']

# Canonical mapping from level name to Python logging integer. Built from
# the stdlib so the allowed set tracks any additions Python makes to the
# core logger vocabulary without editing this module.
_LEVEL_NAME_TO_INT: dict[str, int] = {
    level_name: getattr(logging, level_name)
    for level_name in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
}

# The reverse set is used only for error messages — surface the accepted
# integers alongside the names so the user sees both forms.
_ALLOWED_LEVEL_INTS: frozenset[int] = frozenset(_LEVEL_NAME_TO_INT.values())


def _coerce_log_level(raw_value: Any, field_label: str) -> int:
    # ``Any``: callers pass the raw pre-validation value from a Pydantic
    # ``mode='before'`` validator, which is contractually arbitrary —
    # any YAML scalar the user might write. The isinstance chain below
    # enumerates every accepted shape (``str``, ``int`` excluding
    # ``bool``) and rejects everything else with a clean error pointed at
    # the offending YAML key.
    """
    Convert a user-supplied log level (name or int) to a logging integer.

    Accepts, in order:
        - An ``int`` that matches one of the standard Python logging levels
          (10, 20, 30, 40, 50).
        - A ``str`` naming one of DEBUG / INFO / WARNING / ERROR / CRITICAL
          (case-insensitive, whitespace stripped).

    Args:
        raw_value: The value supplied by the user.
        field_label: Field name used in error messages so failures point
            at the offending YAML key.

    Returns:
        The Python logging integer corresponding to ``raw_value``.

    Raises:
        ValueError: If ``raw_value`` is not a ``str`` or ``int``, is a
            ``bool``, is a string that does not name a known level, or is
            an integer that is not one of the standard levels. ``ValueError``
            (rather than ``TypeError``) is used throughout so Pydantic wraps
            the failure into a ``ValidationError``.
    """
    if isinstance(raw_value, bool):
        # ``bool`` is a subclass of ``int``; reject explicitly to avoid
        # ``True`` quietly mapping to level 1.
        raise ValueError(f'{field_label} must be a log level name or integer, got bool')

    if isinstance(raw_value, int):
        if raw_value not in _ALLOWED_LEVEL_INTS:
            allowed_display: str = ', '.join(
                f'{name}={value}' for name, value in _LEVEL_NAME_TO_INT.items()
            )
            raise ValueError(
                f'{field_label} integer {raw_value} is not a standard log '
                f'level. Allowed: {allowed_display}'
            )
        return raw_value

    if isinstance(raw_value, str):
        normalized: str = raw_value.strip().upper()
        if normalized not in _LEVEL_NAME_TO_INT:
            allowed_display = ', '.join(_LEVEL_NAME_TO_INT)
            raise ValueError(
                f'{field_label} {raw_value!r} is not a recognized log level. '
                f'Allowed: {allowed_display} (case-insensitive)'
            )
        return _LEVEL_NAME_TO_INT[normalized]

    raise ValueError(
        f'{field_label} must be a log level name or integer, '
        f'got {type(raw_value).__name__}'
    )


class LoggerConfig(FrozenModel):
    """
    Logger configuration — console level plus optional file output.

    Console output is always enabled. File output is opt-in: omit
    ``file_path`` (or set it to ``null``) to disable. When ``file_path``
    is set and ``file_level`` is unset, ``file_level`` defaults to
    ``logging.DEBUG`` — the convention is that the file always captures
    at least as much as the console.

    ``console_level`` defaults to ``WARNING``. Library convention is to
    stay quiet by default and let the hosting application opt into
    ``INFO`` or ``DEBUG`` when it wants pyholman's progress output.

    Level fields accept either the standard level name (case-insensitive,
    whitespace tolerated) or the equivalent Python integer. They are
    stored as ``int`` so consumers can pass them directly to
    ``logger.setLevel`` without further translation.
    """

    # Why: ``WARNING`` is the stdlib default for un-configured loggers.
    # Defaulting to the int (rather than the string) skips a needless
    # round-trip through ``_coerce_console_level`` for the default case
    # and keeps the post-validation type ``int`` matching the
    # annotation. The validator still runs for any user-supplied value.
    console_level: int = logging.WARNING
    file_path: Path | None = None
    file_level: int | None = None

    @model_validator(mode='before')
    @classmethod
    def _default_file_level_to_debug(cls, raw_data: Any) -> Any:
        # ``Any`` on both sides: Pydantic ``mode='before'`` validators
        # receive arbitrary pre-validation input — typically a
        # ``dict[str, Any]`` from YAML but sometimes an already-
        # constructed model or any other caller-supplied shape. The
        # isinstance guard below narrows before use.
        """
        When ``file_path`` is set and ``file_level`` is omitted, default
        ``file_level`` to DEBUG so the file always captures detail.

        An explicit ``null`` from the user is preserved (no file output
        level override), because omission and an explicit null mean
        different things at the YAML level.
        """
        if not isinstance(raw_data, dict):
            return raw_data

        typed_data: dict[str, Any] = dict(raw_data)
        # ``dict[str, Any]``: mirrors the runtime shape after the
        # isinstance narrowing above — each YAML value is any scalar the
        # user wrote. Subsequent field validators refine per-column.
        file_path_provided: bool = typed_data.get('file_path') is not None
        file_level_key_missing: bool = 'file_level' not in typed_data

        if file_path_provided and file_level_key_missing:
            typed_data = {**typed_data, 'file_level': logging.DEBUG}

        return typed_data

    @field_validator('console_level', mode='before')
    @classmethod
    def _coerce_console_level(cls, raw_value: Any) -> int:
        # ``Any``: Pydantic ``mode='before'`` validators receive arbitrary
        # pre-validation input. ``_coerce_log_level`` enumerates the
        # accepted shapes and raises for anything else.
        return _coerce_log_level(raw_value, 'console_level')

    @field_validator('file_level', mode='before')
    @classmethod
    def _coerce_file_level(cls, raw_value: Any) -> int | None:
        # ``Any``: same rationale as ``_coerce_console_level`` above.
        if raw_value is None:
            return None
        return _coerce_log_level(raw_value, 'file_level')

    @field_validator('file_path', mode='before')
    @classmethod
    def _expand_and_resolve_file_path(cls, raw_value: Any) -> Path | None:
        # ``Any``: same rationale — arbitrary pre-validation YAML input,
        # narrowed by the isinstance check below.
        """Expand ``~`` and resolve to absolute; ``None`` passes through."""
        if raw_value is None:
            return None
        if not isinstance(raw_value, (str, Path)):
            raise ValueError(
                f'file_path must be a string, Path, or null, '
                f'got {type(raw_value).__name__}'
            )
        return Path(raw_value).expanduser().resolve()
