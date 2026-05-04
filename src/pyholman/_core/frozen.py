# src/pyholman/_core/frozen.py
"""Strict, immutable Pydantic base class for pyholman-controlled schemas."""

from pydantic import ConfigDict

from pyholman._core.base import BaseHolmanModel

__all__: list[str] = ['FrozenModel']


class FrozenModel(BaseHolmanModel):
    """
    Base class for immutable, strictly-validated Pydantic models.

    FrozenModel is the foundational base for all pyholman models whose schema
    is controlled by *us* rather than by an external API. That includes
    configuration models (LoggerConfig, ClientConfig, etc.), query input
    models (VehicleQueryInput), and internal domain models computed by
    pyholman itself.

    Guarantees:
        - **Immutable.** Instances cannot be modified after creation
          (``frozen=True``). To update values, construct a new instance with
          ``model_copy(update={...})``.
        - **Strict.** Unknown fields raise ``ValidationError``
          (``extra='forbid'``). Typos in user configs surface immediately
          rather than being silently dropped.
        - **Defaults validated.** Default values are checked at class
          definition time (``validate_default=True``), catching invalid
          defaults during development rather than at first use.

    When NOT to use this class:
        If the model parses data returned by Holman's API, use
        ``ResponseModel`` instead. Holman may add fields to their responses
        between versions, and ``extra='forbid'`` would make such additions
        break every user installation. ``ResponseModel`` is the tolerant
        counterpart intended for exactly that case.

    Subclassing patterns:
        Subclasses commonly add field validators for domain constraints,
        model validators for cross-field consistency checks, and occasionally
        override ``__repr__`` for domain-specific debug formatting. The
        default ``__repr__`` inherited from ``BaseHolmanModel`` is usually
        sufficient.

    Examples:
        Configuration model::

            class ClientConfig(FrozenModel):
                client_id: str
                base_url: HttpUrl = HttpUrl('https://api.holman.solutions')
                request_timeout_seconds: float = Field(default=30.0, gt=0)

        Query input model::

            class VehicleQueryInput(FrozenModel):
                lessee_codes: list[str] = Field(min_length=1)
                status_codes: list[int] | None = None
                page_size: int = Field(default=200, ge=1, le=1000)
                page_number: int = Field(default=1, ge=1)
    """

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )
