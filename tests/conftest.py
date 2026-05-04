# tests/conftest.py
"""Shared pytest fixtures for the pyholman test suite."""

import pytest

__all__: list[str] = []

# Dummy value used by the autouse fixture below. Tests that need to verify
# behavior when the variable is unset or empty use ``monkeypatch.delenv``
# or ``monkeypatch.setenv`` to override this default.
_DUMMY_CLIENT_SECRET: str = 'test-secret-value'


@pytest.fixture(autouse=True)
def _set_default_holman_client_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Populate ``HOLMAN_CLIENT_SECRET`` for every test by default.

    Individual tests that need the variable unset (or set to a different
    value) can override this with ``monkeypatch.delenv`` or
    ``monkeypatch.setenv`` inside the test body — the monkeypatch applied
    by this fixture is undone at teardown regardless.
    """
    monkeypatch.setenv('HOLMAN_CLIENT_SECRET', _DUMMY_CLIENT_SECRET)
