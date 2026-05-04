# src/pyholman/_yaml/loader.py
"""
YAML loading utilities for pyholman.

This module provides utilities for loading YAML content from two sources:
    - Filesystem paths (user-provided configuration files)
    - Raw strings, bytes, or file-like objects (useful for testing)

Architecture:
    Both callable entry points delegate to a single ``parse_yaml_to_dict()``
    function that handles parsing and structural validation. This ensures
    consistent error handling and messaging regardless of the YAML source.
"""

import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

import yaml

__all__: list[str] = [
    'load_yaml_from_path',
    'parse_yaml_to_dict',
]

logger: logging.Logger = logging.getLogger(__name__)

# Number of offending keys to enumerate in the error message for non-string
# top-level keys. Keeps the exception message bounded on pathological input.
_MAX_BAD_KEY_EXAMPLES: int = 3

_ReadContentType_co = TypeVar('_ReadContentType_co', str, bytes, covariant=True)


class SupportsRead(Protocol[_ReadContentType_co]):
    """
    Structural protocol for file-like objects passed to PyYAML.

    PyYAML's ``safe_load`` accepts any object whose ``read`` method returns
    ``str`` or ``bytes``. This Protocol captures that requirement so callers
    can pass ``io.StringIO``, ``io.BytesIO``, an opened file handle, or any
    other type that matches — without requiring an inheritance relationship.

    The type parameter ``_ReadContentType_co`` is covariant because a caller
    declaring ``SupportsRead[str]`` is satisfied by any producer returning a
    more specific subtype of ``str``. Covariance is safe here because the
    protocol only *returns* content; it never consumes a parameter of the
    type variable.
    """

    def read(self, length: int = -1, /) -> _ReadContentType_co: ...


type YamlSource = str | bytes | SupportsRead[str] | SupportsRead[bytes]


def parse_yaml_to_dict(
    yaml_source: YamlSource,
    source_description: str,
) -> dict[str, Any]:
    # ``Any`` is appropriate for the value type of the returned mapping:
    # YAML values are genuinely heterogeneous (nested dicts, lists, scalars
    # of multiple types) and this parser sits below schema validation. The
    # subsequent Pydantic model_validate call narrows the types.
    """
    Parse a YAML source into a validated top-level dictionary.

    Performs safe parsing (``yaml.safe_load``) and then the minimum
    structural validation required for every pyholman configuration file:
    the document must exist, must decode to a non-empty mapping, and its
    top-level keys must all be strings. Anything else is rejected with a
    message that names the source so callers can trace where a malformed
    file came from.

    Args:
        yaml_source: The YAML content to parse. Accepts a ``str`` or
            ``bytes`` document, or any file-like object whose ``read``
            method returns ``str`` or ``bytes`` (including ``io.StringIO``,
            ``io.BytesIO``, and opened file handles).
        source_description: A short human-readable label for the source
            (filesystem path, ``'<test string>'``, etc.). Included verbatim
            in log records and in every raised exception so errors pinpoint
            their origin.

    Returns:
        The parsed document as a ``dict[str, Any]``. Value types are
        whatever ``yaml.safe_load`` produces; callers layer a Pydantic
        schema on top of this function's output to refine them.

    Raises:
        ValueError: If the YAML is empty (``None``) or parses to an empty
            mapping. Empty configuration files almost always indicate a
            mistake and are worth failing loudly on.
        TypeError: If the YAML root is not a mapping (e.g., a top-level
            list), or if any top-level key is not a string.
        yaml.YAMLError: Propagated from ``yaml.safe_load`` when the input
            is not valid YAML.
    """
    logger.debug('Parsing YAML from: %s', source_description)

    parsed_content: Any = yaml.safe_load(yaml_source)

    if parsed_content is None:
        logger.error('YAML content is empty (None): %s', source_description)
        raise ValueError(
            f'YAML content is empty: {source_description}. '
            f'File may be empty or contain only comments.'
        )

    if not isinstance(parsed_content, dict):
        actual_type_name: str = type(parsed_content).__name__
        logger.error(
            'YAML root must be a dictionary, got %s: %s',
            actual_type_name,
            source_description,
        )
        raise TypeError(
            f'YAML root must be a dictionary, got {actual_type_name}: '
            f'{source_description}'
        )

    if len(parsed_content) == 0:
        logger.error(
            'YAML content is an empty dictionary (no keys): %s',
            source_description,
        )
        raise ValueError(
            f'YAML content is an empty dictionary: {source_description}. '
            f'Configuration files must contain at least one key.'
        )

    non_string_keys: list[tuple[Any, type[Any]]] = [
        (key, type(key))
        for key in parsed_content  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str)
    ]

    if non_string_keys:
        bad_key_examples: list[str] = [
            f'{key!r} ({key_type.__name__})'
            for key, key_type in non_string_keys[:_MAX_BAD_KEY_EXAMPLES]
        ]
        bad_keys_display: str = ', '.join(bad_key_examples)

        if len(non_string_keys) > _MAX_BAD_KEY_EXAMPLES:
            bad_keys_display += f', ... ({len(non_string_keys)} total)'

        logger.error(
            'YAML contains non-string keys: %s in %s',
            bad_keys_display,
            source_description,
        )
        raise TypeError(
            f'YAML keys must be strings, found non-string keys: '
            f'{bad_keys_display} in {source_description}'
        )

    logger.debug(
        'Successfully parsed YAML with %d top-level keys: %s',
        len(parsed_content),
        source_description,
    )

    validated_content: dict[str, Any] = cast(dict[str, Any], parsed_content)

    return validated_content


def load_yaml_from_path(file_path: str | Path) -> dict[str, Any]:
    """
    Load and parse a YAML file from the filesystem.

    The path is expanded (``~`` → home directory) and resolved to an
    absolute path before opening, so the ``FileNotFoundError`` raised by
    ``Path.open`` names the exact location that was attempted. The file
    is opened in binary mode and handed to ``parse_yaml_to_dict`` for
    structural validation — PyYAML detects the encoding itself from the
    byte stream.

    Args:
        file_path: Path to the YAML file. Accepts a string or a ``Path``;
            tilde is expanded and relative paths are resolved against the
            current working directory.

    Returns:
        The parsed document as a ``dict[str, Any]``.

    Raises:
        FileNotFoundError: If the resolved path does not exist. The message
            contains the absolute resolved path.
        PermissionError: If the resolved path exists but cannot be read.
        ValueError: If the file parses to an empty document.
        TypeError: If the file's root is not a mapping, or contains
            non-string top-level keys.
        yaml.YAMLError: If the file is not valid YAML.
    """
    resolved_path: Path = Path(file_path).expanduser().resolve()
    source_description: str = str(resolved_path)

    logger.debug('Loading YAML from filesystem: %s', source_description)

    with resolved_path.open('rb') as file_handle:
        parsed_data: dict[str, Any] = parse_yaml_to_dict(
            yaml_source=file_handle,
            source_description=source_description,
        )

    logger.info('Loaded YAML from filesystem: %s', source_description)

    return parsed_data
