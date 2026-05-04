# src/pyholman/_config/fleet.py
"""Fleet scope section of the user configuration."""

import logging
from typing import Any

from pydantic import field_validator, model_validator

from pyholman._core import FrozenModel

__all__: list[str] = ['FleetConfig']

logger: logging.Logger = logging.getLogger(__name__)

# Every Holman lessee code is exactly four characters wide. Codes are
# case-insensitive on input but canonicalized to uppercase on storage so
# request construction and caching produce stable, comparable keys.
_LESSEE_CODE_LENGTH: int = 4


class FleetConfig(FrozenModel):
    """
    Fleet scope — the lessee codes this pyholman user is authorized to query.

    Holman's API scopes permissions per user; a code outside the user's
    authorization returns empty results rather than an error, which can
    mask misconfiguration. Listing the codes explicitly here lets request
    construction route queries correctly and lets pyholman validate caller
    intent against the user's documented scope.

    YAML shape:

        fleet:
          organization_id: 'ORG1'
          lessee_codes:
            - 'XXXX'

    The ``organization_id`` key in YAML is a convenience for readers —
    Holman returns 404 when child lessee codes are sent without their
    parent, so pyholman merges the organization ID into ``lessee_codes``
    at load time. The merged result is the only view the model exposes;
    ``organization_id`` is not an attribute after validation.

    Codes (including the merged organization ID, if any) are normalized:

        1. Whitespace stripped.
        2. Uppercased.
        3. Required to be exactly four characters after stripping.
        4. Deduplicated.
        5. Sorted ascending.
        6. Stored as an immutable ``tuple[str, ...]``.
    """

    lessee_codes: tuple[str, ...]

    @model_validator(mode='before')
    @classmethod
    def _merge_organization_id_into_lessee_codes(cls, raw_data: Any) -> Any:
        # ``Any``: Pydantic ``mode='before'`` validators receive arbitrary
        # pre-validation input — typically a ``dict[str, Any]`` from YAML
        # but sometimes an already-constructed model or any other caller-
        # supplied shape. The isinstance guard below narrows before use.
        """
        Pop ``organization_id`` from the input and prepend it to ``lessee_codes``.

        Accepts ``str``, ``int``, or ``None``. A ``None``, missing key, or
        empty/whitespace-only string is a no-op: the lessee codes pass
        through untouched. Integers are coerced via ``str()`` so YAML
        users may write bare numbers (``organization_id: 8879``) without
        quoting. Any existing duplicate between the merged ID and the
        lessee codes is handled by the dedup step in the field validator
        below.
        """
        if not isinstance(raw_data, dict):
            return raw_data

        typed_data: dict[str, Any] = dict(raw_data)
        organization_id_value: Any = typed_data.pop('organization_id', None)
        # ``Any`` follows the container type.

        merged_identifier: str | None = _normalize_organization_id(
            organization_id_value
        )
        if merged_identifier is None:
            return typed_data

        existing_codes: Any = typed_data.get('lessee_codes', [])
        # ``Any``: same rationale as ``organization_id_value`` above.
        if not isinstance(existing_codes, (list, tuple)):
            # Let the field validator below produce the canonical error
            # message for bad ``lessee_codes`` shapes rather than
            # duplicating the check here.
            return typed_data

        typed_data['lessee_codes'] = [merged_identifier, *existing_codes]
        return typed_data

    @field_validator('lessee_codes', mode='before')
    @classmethod
    def _normalize_lessee_codes(
        cls,
        raw_value: Any,
    ) -> tuple[str, ...]:
        # ``Any``: Pydantic ``mode='before'`` validators receive arbitrary
        # pre-validation input. The isinstance checks below narrow before
        # use.
        """
        Strip, uppercase, length-check, deduplicate, and sort lessee codes.

        Accepts any sequence of strings (YAML lists arrive as ``list[str]``).
        Rejects empty sequences — a FleetConfig with no codes cannot query
        anything, so it is almost certainly a user mistake.
        """
        if not isinstance(raw_value, (list, tuple)):
            raise ValueError(
                f'lessee_codes must be a list of strings, '
                f'got {type(raw_value).__name__}'
            )

        if len(raw_value) == 0:
            raise ValueError('lessee_codes must contain at least one code')

        normalized_codes: set[str] = set()
        for index, candidate in enumerate(raw_value):
            if not isinstance(candidate, str):
                raise ValueError(
                    f'lessee_codes[{index}] must be a string, '
                    f'got {type(candidate).__name__}'
                )

            stripped_code: str = candidate.strip().upper()
            if len(stripped_code) != _LESSEE_CODE_LENGTH:
                raise ValueError(
                    f'lessee_codes[{index}] must be exactly '
                    f'{_LESSEE_CODE_LENGTH} characters after stripping '
                    f'whitespace, got {len(stripped_code)}: {candidate!r}'
                )

            normalized_codes.add(stripped_code)

        return tuple(sorted(normalized_codes))


def _normalize_organization_id(raw_value: Any) -> str | None:
    # ``Any``: called with the raw YAML value of ``organization_id``,
    # which may be any scalar a user writes in the file. Dispatch below
    # enumerates every accepted shape and rejects the rest.
    """
    Coerce ``raw_value`` to the string form suitable for prepending.

    Returns ``None`` when the caller supplied no organization ID (missing
    key, explicit ``None``, empty string, or whitespace-only string). A
    ``bool`` is rejected loudly even though it is an ``int`` subclass —
    a YAML ``true`` turning into the string ``'True'`` would be a
    silent-fallback bug.
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, bool):
        raise ValueError('organization_id must be a string or integer, got bool')

    if isinstance(raw_value, int):
        return str(raw_value)

    if isinstance(raw_value, str):
        stripped_value: str = raw_value.strip()
        if not stripped_value:
            return None
        return stripped_value

    raise ValueError(
        f'organization_id must be a string or integer, got {type(raw_value).__name__}'
    )
