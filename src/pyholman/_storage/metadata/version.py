# src/pyholman/_storage/metadata/version.py
"""Pyholman package-version detection for sidecar metadata."""

import logging
from importlib.metadata import PackageNotFoundError, version

from pyholman._core.constants import PACKAGE_NAME

__all__: list[str] = ['get_pyholman_version']

logger: logging.Logger = logging.getLogger(__name__)

# Sentinel returned by ``get_pyholman_version`` when the package is not
# installed (e.g., running tests from a source checkout without ``pip
# install -e``). Metadata is diagnostic; a missing version should not
# break persistence.
_UNKNOWN_VERSION: str = 'unknown'


def get_pyholman_version() -> str:
    """
    Return the installed pyholman package version, or ``'unknown'``.

    Returns:
        The string returned by :func:`importlib.metadata.version` for
        the ``pyholman`` distribution. Returns ``'unknown'`` when the
        package is not installed (e.g., running from a source checkout
        without ``pip install -e``). The fallback exists because
        metadata is diagnostic — a missing version must not break a
        write.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        logger.debug(
            '%s not installed; recording pyholman_version=%r in metadata.',
            PACKAGE_NAME,
            _UNKNOWN_VERSION,
        )
        return _UNKNOWN_VERSION
