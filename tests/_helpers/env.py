# tests/_helpers/env.py
"""
Shared environment-patching helpers for the pyholman test suite.

Test-internal — not part of the pyholman public API. Extracted into a
helper so cross-platform tilde-expansion plumbing is defined in one
place rather than duplicated across config and YAML loader tests.
"""

from pathlib import Path

import pytest

__all__: list[str] = ['patch_home_directory']


def patch_home_directory(
    monkeypatch: pytest.MonkeyPatch,
    home_path: Path,
) -> None:
    """
    Make ``~`` expand to ``home_path`` on both POSIX and Windows.

    ``os.path.expanduser`` consults different environment variables on
    each platform: ``HOME`` on POSIX, and ``USERPROFILE`` (then
    ``HOMEDRIVE`` + ``HOMEPATH``) on Windows. Patching ``HOME`` alone
    is a no-op on Windows. This helper sets all of them so the test
    asserts against ``home_path`` deterministically on either platform.

    Args:
        monkeypatch: The pytest monkeypatch fixture for the test.
        home_path: The directory ``~`` should expand to.

    Side Effects:
        Sets ``HOME``, ``USERPROFILE``, ``HOMEDRIVE``, and ``HOMEPATH``
        in the process environment for the lifetime of the test via
        ``monkeypatch.setenv``.
    """
    home_string: str = str(home_path)
    monkeypatch.setenv('HOME', home_string)
    monkeypatch.setenv('USERPROFILE', home_string)
    # On Windows configurations where ``USERPROFILE`` is absent,
    # ``expanduser`` falls back to ``HOMEDRIVE`` + ``HOMEPATH``. Patch
    # those too so the test does not depend on which fallback fires.
    drive: str = home_path.drive
    monkeypatch.setenv('HOMEDRIVE', drive)
    monkeypatch.setenv('HOMEPATH', home_string[len(drive):])
