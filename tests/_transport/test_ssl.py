# tests/_transport/test_ssl.py
"""Tests for the truststore-backed SSL context factory."""

import ssl
import sys

import pytest

from pyholman._transport import build_truststore_ssl_context

__all__: list[str] = []

# The importable-path tests need the real ``truststore`` package. In
# environments without it, skip those tests but still run the fallback
# test that verifies the ImportError → RuntimeError conversion.
try:
    import truststore as _truststore_module
except ImportError:  # pragma: no cover - environment-dependent
    _truststore_module = None  # type: ignore[assignment]


_truststore_required = pytest.mark.skipif(
    _truststore_module is None,
    reason='truststore is not installed in this test environment',
)


class TestBuildTruststoreSslContextAvailable:
    @_truststore_required
    def test_returns_ssl_context_instance(self) -> None:
        ssl_context: ssl.SSLContext = build_truststore_ssl_context()
        assert isinstance(ssl_context, ssl.SSLContext)

    @_truststore_required
    def test_returns_truststore_subclass(self) -> None:
        ssl_context: ssl.SSLContext = build_truststore_ssl_context()
        # ``truststore.SSLContext`` subclasses ``ssl.SSLContext``; the
        # assertion here is what guarantees the returned context actually
        # routes verification through the OS trust store rather than
        # certifi's bundled roots.
        assert _truststore_module is not None  # narrow for the type checker
        assert isinstance(ssl_context, _truststore_module.SSLContext)


class TestBuildTruststoreSslContextMissing:
    def test_missing_truststore_raises_runtime_error_with_install_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Setting a module entry to ``None`` in ``sys.modules`` forces
        # subsequent ``import`` statements for that name to raise
        # ``ImportError`` — documented CPython behavior. No filesystem
        # manipulation or uninstall is needed; monkeypatch tears this
        # down at test end so the real module (if present) remains
        # usable for neighboring tests.
        monkeypatch.setitem(sys.modules, 'truststore', None)

        with pytest.raises(RuntimeError, match='pip install truststore') as excinfo:
            build_truststore_ssl_context()

        assert isinstance(excinfo.value.__cause__, ImportError)
