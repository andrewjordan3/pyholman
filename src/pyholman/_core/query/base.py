# src/pyholman/_core/query/base.py
"""
Base dataclass for Holman query inputs.

``QueryInputBase`` is the description of a single HTTP request against a
Holman endpoint: URL, semantic query filters, headers, and the
response-item model used to validate the JSON that comes back. Pagination
state is *not* part of the query — the client decides which page to fetch
— and is passed per call to ``url()`` / ``query_params()``. Subclasses
set the endpoint path and the response-item type as ``ClassVar``
attributes; the subclass hook enforces both at class-definition time so
a typo fails loudly at import rather than at runtime.

Why a dataclass rather than a Pydantic model:
    Query inputs are assembled in Python from already-validated sources
    (``UserConfig`` plus orchestrator logic) — never from untrusted
    external input. Pydantic's schema machinery buys nothing here and
    pays allocation cost for every pagination step. Frozen slotted
    dataclasses give immutability and memory efficiency without the
    overhead.

Per-field API-key metadata:
    Fields that appear on the URL carry ``metadata={'api_key': '...'}``;
    fields without this metadata (``base_url``) are structural and never
    serialized into the query string. This is opt-in by design — adding
    a new non-parameter field to a subclass does not accidentally leak
    it into the URL.
"""

import logging
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from typing import Any, ClassVar

from pyholman._core.response import ResponseModel
from pyholman._strings import build_url

__all__: list[str] = ['QueryInputBase']

logger: logging.Logger = logging.getLogger(__name__)

# Closed union of value kinds a ``QueryInputBase`` field (or a caller-
# supplied pagination argument) can carry. Covers every shape the
# serialization layer below dispatches on: the base-class fields
# (``tuple[str, ...]``, ``int``, ``datetime``), the pagination arguments
# (``int``), and the extra fields subclasses are known to add
# (``str``, ``bool``, optionally lists/tuples of int). Keeping this
# closed rather than ``Any`` means a new field type that doesn't fit
# fails loudly at the serializer rather than silently collapsing to
# ``str(value)``.
type _QueryFieldValue = (
    bool | int | str | datetime | tuple[str | int, ...] | list[str | int]
)

# Holman wire-protocol parameter names for pagination. Kept here so the
# query-serialization layer is the single source of truth for the names
# that appear on the URL.
_PAGE_NUMBER_API_KEY: str = 'pageNumber'
_PAGE_SIZE_API_KEY: str = 'pageSize'


@dataclass(frozen=True, slots=True, kw_only=True)
class QueryInputBase[TItem: ResponseModel]:
    """
    Base class for endpoint-specific query inputs.

    The type parameter ``TItem`` binds the per-record model that
    parameterizes this query's response envelope. Subclasses supply
    the concrete type both at the type level (``QueryInputBase[Vehicle]``)
    and at runtime via the ``response_item_type`` ``ClassVar``. The
    type parameter flows through :meth:`HolmanClient.send` so that
    ``client.send(VehiclesQuery(...))`` returns
    ``PaginatedResponse[Vehicle]`` — ``response.items`` is typed as
    ``list[Vehicle]`` without the caller having to assert or cast.

    Subclasses describe one Holman endpoint by setting two ``ClassVar``
    attributes:

        endpoint_path: The path appended to ``base_url`` for this
            endpoint (e.g., ``'/CustomerDataAPI/vehicles/get-vehicles'``).
        response_item_type: The ``ResponseModel`` subclass used to
            validate each item inside the paginated envelope. Typed as
            ``ClassVar[type[ResponseModel]]`` rather than
            ``ClassVar[type[TItem]]`` because Python's type system
            does not permit a ``ClassVar`` to reference a type
            parameter. The *type-parameter* binding on the subclass
            carries the specific type through callers; the ``ClassVar``
            annotation here is only a subclass-contract reminder.

    A missing ``ClassVar`` on a subclass raises ``TypeError`` at
    class-definition time via ``__init_subclass__``.

    Instances are frozen slotted dataclasses; values are set at
    construction and never mutate. ``kw_only=True`` prevents positional
    construction so no caller accidentally swaps ``base_url`` with a
    string field, for example.

    Mutual exclusivity note:
        Holman treats ``last_change_record_id`` and ``last_change_date``
        as mutually exclusive. Setting both produces undefined server
        behavior. This class does not enforce the rule — query inputs
        come from orchestrator code, and an orchestrator bug should fail
        loudly against Holman's response, not silently one layer up.

    Attributes:
        base_url: Scheme + host (e.g., ``'https://api.holman.solutions'``).
            Joined with ``endpoint_path`` via
            :func:`pyholman._strings.build_url` to produce the full URL.
            Not a query parameter — has no ``api_key`` metadata.
        lessee_codes: Codes this query is scoped to. Required; callers
            always pass ``config.fleet.lessee_codes``. Serialized to the
            wire as a comma-joined string (``lesseeCodes=XXXX,YYYY``).
        last_change_record_id: Cursor for ID-based delta pagination. See
            the mutual-exclusivity note above.
        last_change_date: Cursor for date-based delta pagination. Must
            be tz-aware UTC; serialized as ISO 8601 with ``Z`` suffix.
    """

    endpoint_path: ClassVar[str]
    response_item_type: ClassVar[type[ResponseModel]]

    base_url: str
    lessee_codes: tuple[str, ...] = field(metadata={'api_key': 'lesseeCodes'})
    last_change_record_id: int | None = field(
        default=None,
        metadata={'api_key': 'lastChangeRecordId'},
    )
    last_change_date: datetime | None = field(
        default=None,
        metadata={'api_key': 'lastChangeDate'},
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # ``Any`` is conventional for this hook — Python's subclass
        # machinery forwards arbitrary keyword arguments (``metaclass=``,
        # PEP 487 keyword arguments) and a narrower annotation would
        # silently reject callers that use them.
        """
        Enforce that every subclass sets both required ``ClassVar`` attributes.

        Args:
            **kwargs: Class-creation keyword arguments forwarded to
                ``super().__init_subclass__``.

        Raises:
            TypeError: If ``endpoint_path`` or ``response_item_type`` is
                not defined directly on the subclass.
        """
        # ``@dataclass(slots=True)`` rebinds the class object to a new
        # slotted class, which breaks the zero-argument ``super()`` form
        # (``__class__`` resolved at compile time no longer matches the
        # final class). Forwarding via ``object.__init_subclass__`` keeps
        # the PEP 487 chain intact while sidestepping the slots bug.
        object.__init_subclass__(**kwargs)
        if 'endpoint_path' not in cls.__dict__:
            raise TypeError(f'{cls.__name__} must define ClassVar endpoint_path')
        if 'response_item_type' not in cls.__dict__:
            raise TypeError(f'{cls.__name__} must define ClassVar response_item_type')

    def url(self, page_number: int, page_size: int) -> str:
        """
        Return the fully formed URL for one page of this query.

        Delegates to :func:`pyholman._strings.build_url`, which handles
        base/path slash normalization and query-parameter URL-encoding
        uniformly with the other call site (token-endpoint URL
        construction in ``TokenManager``).

        Args:
            page_number: 1-indexed page to request. Holman paginates
                from 1, not 0.
            page_size: Items per page. Chosen by the client from
                ``config.api.page_size``; Holman's server-side cap is
                1000.

        Returns:
            The request URL as a string.
        """
        return build_url(
            base_url=self.base_url,
            path=self.endpoint_path,
            query_params=self.query_params(
                page_number=page_number, page_size=page_size
            ),
        )

    def query_params(self, page_number: int, page_size: int) -> dict[str, str]:
        """
        Return the query parameters keyed by Holman's wire names.

        Walks this dataclass's fields, skips those without an
        ``api_key`` entry in their metadata, skips fields whose current
        value is ``None``, and serializes everything else via
        ``_serialize_query_value``. Merges the caller-supplied pagination
        state in under ``pageNumber`` and ``pageSize``.

        Args:
            page_number: 1-indexed page to request.
            page_size: Items per page.

        Returns:
            A plain ``dict`` suitable for :func:`urllib.parse.urlencode`.
            Values are already strings; ``urlencode`` only percent-escapes.

        Raises:
            ValueError: If a ``datetime`` field is naive or not UTC.
        """
        params: dict[str, str] = {}
        for field_definition in fields(self):
            api_key: str | None = field_definition.metadata.get('api_key')
            if api_key is None:
                continue
            field_value: _QueryFieldValue | None = getattr(self, field_definition.name)
            if field_value is None:
                continue
            params[api_key] = _serialize_query_value(field_value)
        params[_PAGE_NUMBER_API_KEY] = _serialize_query_value(page_number)
        params[_PAGE_SIZE_API_KEY] = _serialize_query_value(page_size)
        return params

    def headers(self) -> dict[str, str]:
        """Return the HTTP headers this query requires."""
        return {'Accept': 'application/json'}


def _serialize_query_value(value: _QueryFieldValue) -> str:
    """
    Serialize a single query-parameter value to its wire form.

    Order matters: ``bool`` is checked before ``int`` because
    :class:`bool` is an int subclass, and a naive ``isinstance(value, int)``
    check would coerce booleans to ``'1'`` / ``'0'`` rather than the
    ``'true'`` / ``'false'`` Holman expects.

    Sequences are comma-joined before being passed to ``urlencode``;
    ``urlencode`` then percent-escapes the already-joined string. This
    matches Holman's wire convention (``lesseeCodes=XXXX,YYYY``).

    Args:
        value: The field value to serialize.

    Returns:
        The wire-form string.

    Raises:
        ValueError: If ``value`` is a naive datetime or a tz-aware
            datetime whose offset is not UTC.
    """
    match value:
        case bool():
            return 'true' if value else 'false'
        case tuple() | list():
            return ','.join(str(element) for element in value)
        case datetime():
            if value.tzinfo is None:
                raise ValueError(
                    f'datetime query values must be timezone-aware UTC; '
                    f'got naive {value.isoformat()}'
                )
            if value.utcoffset() != timedelta(0):
                raise ValueError(
                    f'datetime query values must be in UTC; got offset '
                    f'{value.utcoffset()} ({value.isoformat()})'
                )
            # Holman's wire format is ``yyyy-MM-ddTHH:mm:ss.fffZ`` — exactly
            # three fractional digits (milliseconds). Sub-millisecond
            # precision is truncated, not rounded: integer division of
            # ``microsecond`` by 1000 drops the lower three digits without
            # carrying, which matches the server's own parsing behavior.
            milliseconds: int = value.microsecond // 1000
            return (
                f'{value.year:04d}-{value.month:02d}-{value.day:02d}'
                f'T{value.hour:02d}:{value.minute:02d}:{value.second:02d}'
                f'.{milliseconds:03d}Z'
            )
        case _:
            return str(value)
