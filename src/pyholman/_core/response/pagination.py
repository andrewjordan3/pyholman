# src/pyholman/_core/response/pagination.py
"""
Pagination envelope shared by every Holman response.

Live responses from the vehicles, contacts, and maintenance endpoints
use an identical envelope:

    {
      "statusCode": 200,
      "totalCount": 4744,
      "pageInfo": {"pageNumber": 1, "pageSize": 5,
                   "totalPages": 949, "lastChangeRecordId": null},
      "items": [...]
    }

Empty responses drop ``pageInfo`` and carry a short ``message``:

    {"statusCode": 200, "totalCount": 0,
     "message": "No data found.", "items": []}

Pydantic aliases stay camelCase because they map to Holman's wire
format. Python attribute names are snake_case, which is what the rest
of pyholman — DataFrames, metadata JSON, orchestrator code — deals in.
"""

import logging

from pydantic import Field

from pyholman._core.response.base import ResponseModel

__all__: list[str] = [
    'PageInfo',
    'PaginatedResponse',
]

logger: logging.Logger = logging.getLogger(__name__)


class PageInfo(ResponseModel):
    """
    Pagination metadata present on non-empty Holman responses.

    Attributes:
        page_number: 1-indexed page number that was returned.
        page_size: Number of items per page (Holman's server-side cap,
            typically 200).
        total_pages: Total pages available for the current query. Zero
            when the query matches no records, though in practice
            Holman omits ``pageInfo`` entirely in that case.
        last_change_record_id: Cursor hint sometimes emitted by delta
            queries. ``None`` on endpoints/queries that do not paginate
            by record ID.
    """

    page_number: int = Field(alias='pageNumber', ge=1)
    page_size: int = Field(alias='pageSize', ge=1)
    total_pages: int = Field(alias='totalPages', ge=0)
    last_change_record_id: int | None = Field(
        alias='lastChangeRecordId',
        default=None,
    )


class PaginatedResponse[TItem: ResponseModel](ResponseModel):
    """
    Envelope returned by every paginated Holman endpoint.

    The generic type parameter ``TItem`` identifies the per-record model
    the client parameterizes at runtime (e.g., ``PaginatedResponse[VehicleResponse]``).
    A concrete item type is not required to deserialize the envelope —
    callers that only need the status code, total count, or pagination
    cursor can use ``PaginatedResponse`` directly.

    Attributes:
        status_code: Holman's reported ``statusCode``. Normally mirrors
            the HTTP status.
        total_count: Total number of records matching the query across
            all pages.
        page_info: Pagination metadata when the response carries rows;
            ``None`` on empty responses (Holman omits the key entirely).
        items: The page of records. Empty list when ``total_count`` is
            zero or the requested page is past the end.
        message: Optional human-readable note, e.g., ``'No data found.'``
            on empty responses.
    """

    status_code: int = Field(alias='statusCode')
    total_count: int = Field(alias='totalCount', ge=0)
    page_info: PageInfo | None = Field(alias='pageInfo', default=None)
    items: list[TItem] = Field(default_factory=list)
    message: str | None = None
