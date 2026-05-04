# tests/_core/response/test_base.py
"""Tests for ResponseModel's tolerant / populate-by-name policy."""

import pytest
from pydantic import Field, ValidationError

from pyholman._core import ResponseModel

__all__: list[str] = []


class _Example(ResponseModel):
    identifier: int = Field(alias='id')
    label: str = Field(alias='lbl')


class TestResponseModelTolerance:
    def test_extra_fields_silently_dropped(self) -> None:
        # ``extra='ignore'`` — unknown keys in the input are dropped without
        # raising, so a new Holman-side field does not break the library.
        instance: _Example = _Example.model_validate(
            {'id': 1, 'lbl': 'x', 'unexpected': 'dropped'}
        )
        assert instance.identifier == 1
        assert instance.label == 'x'
        assert not hasattr(instance, 'unexpected')

    def test_declared_fields_required(self) -> None:
        with pytest.raises(ValidationError):
            _Example.model_validate({'id': 1})


class TestResponseModelPopulateByName:
    def test_snake_case_construction_accepted(self) -> None:
        instance: _Example = _Example(identifier=1, label='x')
        assert instance.identifier == 1
        assert instance.label == 'x'

    def test_alias_construction_accepted(self) -> None:
        instance: _Example = _Example.model_validate({'id': 1, 'lbl': 'x'})
        assert instance.identifier == 1
        assert instance.label == 'x'


class TestResponseModelImmutability:
    def test_assignment_to_field_raises(self) -> None:
        instance: _Example = _Example(identifier=1, label='x')
        with pytest.raises(ValidationError):
            instance.identifier = 2  # type: ignore[misc]


class _StringModel(ResponseModel):
    """Single-field tolerant model for the string-stripping tests."""

    label: str | None = None
    quantity: int | None = None


class TestResponseModelStripsStringWhitespace:
    """
    Coverage for the base-class ``@model_validator(mode='before')`` that
    normalizes Holman's wire-format whitespace inconsistency before any
    field validator runs.
    """

    def test_leading_whitespace_stripped(self) -> None:
        instance: _StringModel = _StringModel.model_validate({'label': '   value'})
        assert instance.label == 'value'

    def test_trailing_whitespace_stripped(self) -> None:
        instance: _StringModel = _StringModel.model_validate({'label': 'value   '})
        assert instance.label == 'value'

    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        instance: _StringModel = _StringModel.model_validate({'label': '  value  '})
        assert instance.label == 'value'

    def test_all_whitespace_collapses_to_empty_string(self) -> None:
        # The base validator strips; it does not coerce ``""`` to
        # ``None``. That decision belongs to per-field validators.
        instance: _StringModel = _StringModel.model_validate({'label': '   '})
        assert instance.label == ''

    def test_non_string_field_passes_through(self) -> None:
        instance: _StringModel = _StringModel.model_validate({'quantity': 42})
        assert instance.quantity == 42

    def test_explicit_none_passes_through(self) -> None:
        instance: _StringModel = _StringModel.model_validate(
            {'label': None, 'quantity': None}
        )
        assert instance.label is None
        assert instance.quantity is None
