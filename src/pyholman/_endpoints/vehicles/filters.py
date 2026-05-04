# src/pyholman/_endpoints/vehicles/filters.py
"""
User-facing filter model for the vehicles endpoint.

``VehiclesFilters`` is the strict Pydantic schema the YAML loader
validates ``resources[].filters`` against. It is deliberately decoupled
from :class:`VehiclesQuery` — the transport dataclass — so the two
layers can evolve independently: validation errors surface at config
load with user-friendly messages, and the transport layer consumes only
already-validated values.
"""

from pydantic import computed_field, field_validator

from pyholman._core import IncrementalFilters

__all__: list[str] = ['VehiclesFilters']

# Holman statusCode for sold assets. Presence of this value in
# ``status_codes`` drives the computed ``sold_date_code``.
_SOLD_STATUS_CODE: int = 3

# Valid Holman statusCodes for the vehicles endpoint: 0 (ordered),
# 1 (active), 2 (out-of-service), 3 (sold). Any other value is rejected
# before a request is built.
_VALID_STATUS_CODES: frozenset[int] = frozenset({0, 1, 2, _SOLD_STATUS_CODE})

# Holman requires a ``soldDateCode`` whenever ``statusCodes`` includes
# 3 (sold). Value 5 means "all sold assets regardless of sale date",
# which matches the orchestrator's pull-everything intent.
_SOLD_DATE_CODE_ALL_SOLD: int = 5


class VehiclesFilters(IncrementalFilters):
    """
    Validated user-facing filters for the vehicles endpoint.

    Users author these values in YAML under ``resources[].filters``; the
    YAML loader round-trips them through this model so typos and
    out-of-range values surface at config-load time rather than as a
    400 from Holman.

    Inherits from :class:`IncrementalFilters` — supplies the
    ``last_change_date`` cursor field and the ``with_window_start``
    override for incremental refresh runs.

    Attributes:
        status_codes: Optional tuple of Holman statusCodes to include.
            Every member must be one of ``0``, ``1``, ``2``, ``3``.
            ``None`` means "no status filter".
    """

    status_codes: tuple[int, ...] | None = None

    @field_validator('status_codes')
    @classmethod
    def _validate_status_codes(
        cls, value: tuple[int, ...] | None
    ) -> tuple[int, ...] | None:
        if value is None:
            return None
        invalid_entries: tuple[int, ...] = tuple(
            code for code in value if code not in _VALID_STATUS_CODES
        )
        if invalid_entries:
            raise ValueError(
                f'status_codes entries must be one of '
                f'{sorted(_VALID_STATUS_CODES)}; got invalid {list(invalid_entries)}'
            )
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sold_date_code(self) -> int | None:
        """
        Holman's ``soldDateCode`` derived from ``status_codes``.

        Holman requires a ``soldDateCode`` whenever ``statusCodes``
        contains ``3`` (sold). pyholman always pulls the full history,
        so the derived value is ``5`` ("all sold assets regardless of
        sale date") — never exposed as an input, never configurable by
        users. Returning ``None`` when ``3`` is absent keeps the query
        string free of the parameter on non-sold queries.

        Returns:
            ``5`` when ``status_codes`` includes ``3``; otherwise
            ``None``.
        """
        if self.status_codes is None:
            return None
        if _SOLD_STATUS_CODE in self.status_codes:
            return _SOLD_DATE_CODE_ALL_SOLD
        return None
