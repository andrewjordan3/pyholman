# tests/_core/test_frozen.py
"""Tests for FrozenModel's strict immutability / extra-forbid policy."""

import pytest
from pydantic import ValidationError

from pyholman._core import FrozenModel

__all__: list[str] = []


class _Example(FrozenModel):
    identifier: int
    label: str


class TestFrozenModelStrictness:
    def test_rejects_unknown_field_at_construction(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            _Example(identifier=1, label='x', unknown=42)  # type: ignore[call-arg]

    def test_accepts_declared_fields(self) -> None:
        instance: _Example = _Example(identifier=1, label='x')
        assert instance.identifier == 1
        assert instance.label == 'x'


class TestFrozenModelImmutability:
    def test_assignment_to_field_raises(self) -> None:
        instance: _Example = _Example(identifier=1, label='x')
        with pytest.raises(ValidationError):
            instance.identifier = 2  # type: ignore[misc]

    def test_model_copy_returns_new_instance(self) -> None:
        instance: _Example = _Example(identifier=1, label='x')
        updated: _Example = instance.model_copy(update={'identifier': 2})
        assert instance.identifier == 1
        assert updated.identifier == 2
