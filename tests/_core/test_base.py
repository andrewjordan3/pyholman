# tests/_core/test_base.py
"""Tests for BaseHolmanModel — the shared low-level Pydantic base class."""

from pydantic import ConfigDict, Field
from pydantic.fields import FieldInfo

from pyholman._core.base import BaseHolmanModel

__all__: list[str] = []


class _ExampleModel(BaseHolmanModel):
    """Minimal concrete subclass used to exercise shared behavior."""

    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    identifier: int
    label: str
    note: str | None = None


class TestGetFieldDefinitions:
    def test_returns_field_info_for_every_declared_field(self) -> None:
        definitions: dict[str, FieldInfo] = _ExampleModel.get_field_definitions()
        assert set(definitions.keys()) == {'identifier', 'label', 'note'}
        for field_info in definitions.values():
            assert isinstance(field_info, FieldInfo)

    def test_callable_on_instance_and_class_returns_same_keys(self) -> None:
        class_side: dict[str, FieldInfo] = _ExampleModel.get_field_definitions()
        instance: _ExampleModel = _ExampleModel(identifier=1, label='x')
        instance_side: dict[str, FieldInfo] = instance.get_field_definitions()
        assert list(class_side.keys()) == list(instance_side.keys())


class TestRepr:
    def test_repr_renders_class_name_and_every_field(self) -> None:
        instance: _ExampleModel = _ExampleModel(identifier=42, label='alpha')
        rendered: str = repr(instance)
        assert rendered.startswith('_ExampleModel(')
        assert 'identifier=42' in rendered
        assert "label='alpha'" in rendered
        assert 'note=None' in rendered

    def test_repr_none_field_renders_as_literal_none(self) -> None:
        instance: _ExampleModel = _ExampleModel(identifier=1, label='x', note=None)
        assert 'note=None' in repr(instance)

    def test_repr_long_string_is_truncated(self) -> None:
        # The shared helper in _utils/repr.py truncates at 200 chars; use a
        # short class to keep the assertion focused on the truncation output.
        class _OneField(BaseHolmanModel):
            model_config = ConfigDict(extra='forbid', frozen=True)

            note: str

        long_note: str = 'n' * 500
        instance: _OneField = _OneField(note=long_note)
        rendered: str = repr(instance)
        assert '500 chars' in rendered
        assert 'n' * 200 in rendered

    def test_repr_nested_model_uses_nested_repr(self) -> None:
        class _Inner(BaseHolmanModel):
            model_config = ConfigDict(extra='forbid', frozen=True)

            value: int = Field(default=0)

        class _Outer(BaseHolmanModel):
            model_config = ConfigDict(extra='forbid', frozen=True)

            inner: _Inner

        outer: _Outer = _Outer(inner=_Inner(value=7))
        rendered: str = repr(outer)
        assert 'inner=_Inner(value=7)' in rendered
