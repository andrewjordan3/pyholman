# src/pyholman/_strings/repr.py
"""Compact, truncated value rendering for ``__repr__`` output."""

import logging
from typing import Any, Final

__all__: list[str] = ['format_value_for_repr']

logger: logging.Logger = logging.getLogger(__name__)


# Truncation threshold for a single value rendered inside ``__repr__`` output.
# Values longer than this (strings measured by raw length; other types by the
# length of their ``repr()``) are replaced with a prefix-plus-marker form so
# log lines stay bounded even when a value is multi-KB (a dumped HTML error
# page, a serialized nested structure, a long concatenated note field).
_MAX_VALUE_LENGTH: Final[int] = 200


def format_value_for_repr(value: Any) -> str:
    # ``Any`` is justified: this helper is genuinely generic across every
    # Python value a Pydantic field or an exception attribute can hold —
    # ``None``, scalars, enums, ``datetime``, nested ``BaseModel``,
    # containers, user-defined types. Dispatch below distinguishes the two
    # cases that matter for formatting (``None`` and ``str``) and falls
    # back to :func:`repr` for everything else.
    """
    Render an arbitrary value as a compact, single-line string for repr output.

    Dispatch:

        - ``None`` returns the literal string ``'None'`` (unquoted).
        - A ``str`` is quoted with single quotes and, if longer than
          ``_MAX_VALUE_LENGTH``, truncated to that many characters and
          followed by ``"...' (N chars)"`` where ``N`` is the original
          length.
        - Any other value is rendered via :func:`repr`. If the resulting
          string is longer than ``_MAX_VALUE_LENGTH``, the same
          truncate-with-marker form is applied; the leading quote is
          included to make the truncation visually consistent with the
          string case.

    Args:
        value: The value to render. Any Python object is accepted.

    Returns:
        A single-line string suitable for inclusion in a
        ``ClassName(field=value, ...)`` repr. Contains no newlines.
    """
    if value is None:
        return 'None'

    if isinstance(value, str):
        if len(value) > _MAX_VALUE_LENGTH:
            return f"'{value[:_MAX_VALUE_LENGTH]}...' ({len(value)} chars)"
        return f"'{value}'"

    rendered: str = repr(value)
    if len(rendered) > _MAX_VALUE_LENGTH:
        return f"'{rendered[:_MAX_VALUE_LENGTH]}...' ({len(rendered)} chars)"
    return rendered
