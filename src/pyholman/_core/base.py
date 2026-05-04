# src/pyholman/_core/base.py
"""
Low-level Pydantic base class shared by :class:`FrozenModel` and
:class:`ResponseModel`.

``BaseHolmanModel`` carries the behavior every pyholman model needs
regardless of its strictness policy: a compact, truncated ``__repr__``
backed by :func:`pyholman._strings.format_value_for_repr`, and a
:meth:`get_field_definitions` classmethod that wraps Pydantic V2's
class-level ``model_fields`` attribute.

Most application code should inherit from ``FrozenModel`` (strict) or
``ResponseModel`` (tolerant) instead. ``BaseHolmanModel`` exists as the
shared base the two concrete subclasses extend; they import it directly
from this module (``from pyholman._core.base import BaseHolmanModel``)
rather than through ``pyholman._core``, since both live inside the same
package and reaching siblings via the parent's ``__init__.py`` would
invert the documented import direction.
"""

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from pyholman._strings import format_value_for_repr

__all__: list[str] = ['BaseHolmanModel']


class BaseHolmanModel(BaseModel):
    """
    Shared base class for every pyholman Pydantic model.

    Holds the compact ``__repr__`` implementation and the
    ``get_field_definitions`` classmethod used by
    :class:`pyholman._core.FrozenModel` and
    :class:`pyholman._core.ResponseModel`. The two concrete subclasses
    differ only in their ``model_config`` — in particular, their
    ``extra`` policy and, for responses, alias handling.

    Most users want ``FrozenModel`` (for configs, query inputs, internal
    domain objects) or ``ResponseModel`` (for API response parsing). A
    direct subclass of ``BaseHolmanModel`` is unusual and almost always
    wrong — you would be reinventing one of the two existing policies
    without its tests or its docstring contract.
    """

    # No model_config here: subclasses supply their own, and declaring an
    # empty config on this base would be a no-op that Pydantic has to merge.

    @classmethod
    def get_field_definitions(cls) -> dict[str, FieldInfo]:
        """
        Return the model's field definitions keyed by field name.

        This classmethod exists because Pydantic V2 deprecated accessing
        ``model_fields`` on *instances* — it is a class-level attribute.
        ``get_field_definitions`` provides a consistent interface that works
        identically whether called on the class or an instance, shielding
        caller code from the underlying attribute access rules.

        Returns:
            A dictionary mapping each declared field name to its Pydantic
            ``FieldInfo`` metadata (type, default, constraints, description,
            and so on).

        Example:
            >>> ClientConfig.get_field_definitions().keys()
            dict_keys(['client_id', 'base_url', 'request_timeout_seconds'])
        """
        return cls.model_fields

    def __repr__(self) -> str:
        """
        Return a compact, truncated string representation for debugging.

        Iterates over all declared fields, formats each value using
        :func:`pyholman._strings.format_value_for_repr`, and assembles them
        into a ``ClassName(field=value, field=value)`` form.

        Long strings, and any other value whose ``repr()`` exceeds the
        shared truncation threshold, are rendered with an ellipsis
        marker so debug output stays bounded regardless of model size.

        For ``FrozenModel`` subclasses, extras are impossible
        (``extra='forbid'`` rejects them at construction). For
        ``ResponseModel`` subclasses, extras are silently dropped at
        construction (``extra='ignore'``) and therefore never appear
        here either.

        Returns:
            A single-line string suitable for logging, REPL inspection,
            and inclusion in exception messages.
        """
        field_representations: list[str] = []
        for field_name in self.__class__.model_fields:
            field_value = getattr(self, field_name)
            compact_value: str = format_value_for_repr(field_value)
            field_representations.append(f'{field_name}={compact_value}')

        return f'{self.__class__.__name__}({", ".join(field_representations)})'
