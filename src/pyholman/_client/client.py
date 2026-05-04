# src/pyholman/_client/client.py
"""
Internal client for Holman's Customer Data API.

:class:`HolmanClient` is the package-private composition root that owns
the HTTP transport, the OAuth2 token lifecycle, and the per-endpoint
request building. The orchestrator is the intended consumer;
library users drive pyholman through the public
``fetch`` / ``Orchestrator`` surface rather than by constructing this
class directly.

Three methods make up the internal surface:

    - :meth:`HolmanClient.send` — fetch a single page of results.
    - :meth:`HolmanClient.iter_pages` — yield each page in sequence.
    - :meth:`HolmanClient.collect` — accumulate every page into a
      single list.

The client holds an :class:`httpx.Client` underneath, so it needs to
be closed when finished. Use it as a context manager — the canonical
shape is documented on the class docstring.
"""

import logging
from collections.abc import Iterator
from types import TracebackType
from typing import Self

import httpx

from pyholman._auth import TokenManager
from pyholman._clock import SystemClock
from pyholman._config import UserConfig
from pyholman._core import PaginatedResponse, QueryInputBase, ResponseModel
from pyholman._transport import (
    HttpTransport,
    build_transport,
    parse_response_body,
    send_request,
)

__all__: list[str] = ['HolmanClient']

logger: logging.Logger = logging.getLogger(__name__)

# First page number for every paginated query. Holman paginates from 1,
# not 0. Declared as a module constant so the ``send`` default and the
# ``iter_pages`` loop start from the same source of truth.
_FIRST_PAGE_NUMBER: int = 1


class HolmanClient:
    """
    High-level client for Holman's Customer Data API.

    Construct once per process with a loaded :class:`UserConfig`. Use
    as a context manager so the underlying ``httpx.Client`` is closed
    cleanly when the block exits::

        with HolmanClient(user_config) as client:
            response = client.send(VehiclesQuery(...))
            for page in client.iter_pages(VehiclesQuery(...)):
                process(page.items)

    Not thread-safe. Each thread or process should build its own
    instance; the :class:`TokenManager` embedded in this class does not
    guard its cache with a lock.

    Attributes are private. The public surface is the three methods
    above plus :meth:`close` for callers who cannot use the ``with``
    form.
    """

    def __init__(self, user_config: UserConfig) -> None:
        """
        Construct a client from a loaded :class:`UserConfig`.

        Side Effects:
            Builds an :class:`HttpTransport` (and the underlying
            ``httpx.Client``) immediately. The caller must either use
            the returned instance as a context manager or call
            :meth:`close` when finished to release pooled connections.

        Args:
            user_config: The fully-loaded user configuration.
                ``HolmanClient`` reads ``api`` (base URL, page size,
                truststore selection), ``retry`` (retry policy), and
                — via :class:`TokenManager` — ``credentials`` (OAuth2).
                The remaining sections are stored on ``self._user_config``
                but never read by the client itself.
        """
        self._user_config: UserConfig = user_config
        self._transport: HttpTransport = build_transport(
            user_config.api,
            user_config.retry,
            clock=SystemClock(),
        )
        self._token_manager: TokenManager = TokenManager(user_config, self._transport)

    # -------------------------------------------------------------------------
    # Context manager
    # -------------------------------------------------------------------------

    def __enter__(self) -> Self:
        """Return ``self`` so ``with HolmanClient(...) as client:`` binds correctly."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        Close the underlying HTTP client on exit.

        Returns ``None`` (implicitly) rather than a truthy value, so
        any exception raised inside the ``with`` body propagates — the
        client only guarantees the connection pool is released, not
        that failures are swallowed.
        """
        del exc_type, exc_value, traceback  # Unused — we never suppress.
        self.close()

    def close(self) -> None:
        """
        Close the underlying HTTP client.

        Idempotent: ``httpx.Client.close`` may be called any number of
        times without error, so calling ``close`` after the context
        manager has already closed the client is safe.
        """
        self._transport.client.close()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def send[TItem: ResponseModel](
        self,
        query: QueryInputBase[TItem],
        page_number: int = _FIRST_PAGE_NUMBER,
    ) -> PaginatedResponse[TItem]:
        """
        Fetch a single page of results for ``query``.

        The per-endpoint item type parameter on ``query`` flows through
        to the return type: ``client.send(VehiclesQuery(...))`` is
        typed as ``PaginatedResponse[Vehicle]`` and
        ``response.items`` is ``list[Vehicle]``. The runtime
        parameterization of the envelope matches the static type — the
        same ``ResponseModel`` subclass is used for both.

        Args:
            query: An endpoint-specific :class:`QueryInputBase`
                subclass carrying the base URL, lessee codes, and any
                endpoint-specific filters.
            page_number: 1-indexed page to fetch. Holman paginates from
                1, not 0. Defaults to the first page.

        Returns:
            A :class:`PaginatedResponse` envelope with ``items``,
            ``page_info``, ``total_count``, and optionally ``message``.

        Raises:
            HolmanError: For 4xx responses (other than 429), unexpected
                response shapes, or any non-retryable client error.
            TransientHolmanError: For 5xx responses (and network
                errors) that exhaust the retry budget. Tenacity is
                configured with ``reraise=True``, so the exception
                surfaces as ``TransientHolmanError`` — not wrapped in a
                ``RetryError``.
            RateLimitError: For 429 responses that exhaust the retry
                budget. ``RateLimitError`` is a ``TransientHolmanError``
                subclass; callers catching the parent will catch both.
                ``reraise=True`` preserves the concrete subclass on
                exhaustion.
        """
        page_size: int = self._user_config.api.page_size
        target_url: str = query.url(page_number=page_number, page_size=page_size)
        logger.debug(
            'Sending request to %s (page %d).', query.endpoint_path, page_number
        )

        # Bearer header is fetched per request: on a cache hit it's a
        # dict construction, on a cache miss it transparently refreshes.
        # Attaching it to the long-lived ``httpx.Client`` instead would
        # tie token rotation to client construction.
        auth_headers: dict[str, str] = self._token_manager.get_auth_header()
        combined_headers: dict[str, str] = {**query.headers(), **auth_headers}
        request: httpx.Request = self._transport.client.build_request(
            method='GET',
            url=target_url,
            headers=combined_headers,
        )
        response: httpx.Response = send_request(self._transport, request)

        # Pydantic v2's class-getitem parameterization: builds a concrete
        # ``PaginatedResponse[Vehicle]`` (or whatever the query's
        # response item type is) at runtime so ``items`` is a list of
        # the right subclass, not the base ``ResponseModel``. mypy
        # cannot reason about subscripting with a runtime ``type``
        # value, so we lift the item type to a local before indexing
        # and type-ignore the subscription expression narrowly. The
        # declared generic parameter ``TItem`` matches
        # ``query.response_item_type`` by the subclass contract; the
        # cast on the return keeps the caller-visible type precise.
        response_item_type: type[ResponseModel] = query.response_item_type
        # ``type: ignore[valid-type]`` on the subscription arm: mypy
        # flags runtime ``type[...]`` values as non-type arguments to
        # ``__class_getitem__``. The subclass contract on
        # ``QueryInputBase[TItem]`` guarantees that
        # ``response_item_type`` is the runtime form of ``TItem``; the
        # explicit ``type[PaginatedResponse[TItem]]`` annotation on the
        # left carries the narrowing forward for the rest of the method.
        paginated_response_model: type[PaginatedResponse[TItem]] = PaginatedResponse[
            response_item_type  # type: ignore[valid-type]
        ]
        parsed_response: PaginatedResponse[TItem] = parse_response_body(
            response, paginated_response_model, query.endpoint_path
        )

        total_pages: int | None = (
            parsed_response.page_info.total_pages
            if parsed_response.page_info is not None
            else None
        )
        logger.debug(
            'Received %d items from %s (page %d of %s).',
            len(parsed_response.items),
            query.endpoint_path,
            page_number,
            total_pages if total_pages is not None else 'unknown',
        )
        return parsed_response

    def iter_pages[TItem: ResponseModel](
        self,
        query: QueryInputBase[TItem],
    ) -> Iterator[PaginatedResponse[TItem]]:
        """
        Iterate every page of ``query``, yielding one page at a time.

        Terminates when Holman returns an empty page, an envelope
        without pagination metadata, or signals via
        ``page_info.total_pages`` that the current page was the last.
        Exceptions raised by :meth:`send` propagate to the caller;
        pages yielded before an error are not rolled back.

        The type parameter ``TItem`` flows from :meth:`send`, so the
        yielded envelopes' ``items`` are typed as the endpoint's
        concrete response model (e.g. ``list[Vehicle]``).

        Args:
            query: An endpoint-specific :class:`QueryInputBase`
                subclass. The same ``query`` instance is reused for
                every page — pagination state is passed per call, not
                stored on the query.

        Yields:
            :class:`PaginatedResponse` envelopes, in order, for pages
            starting at 1.

        Raises:
            HolmanError / TransientHolmanError / RateLimitError:
                Propagated from :meth:`send` on the in-flight page. See
                that method's ``Raises`` section for the dispatch rules.
        """
        logger.debug('Iterating pages for %s.', query.endpoint_path)
        pages_yielded: int = 0
        page_number: int = _FIRST_PAGE_NUMBER
        while True:
            response: PaginatedResponse[TItem] = self.send(
                query, page_number=page_number
            )
            # Holman's empty-result envelope omits ``page_info`` and
            # carries ``message: 'No data found.'`` with an empty
            # ``items`` list. The ``not items`` check covers both that
            # case and "the caller asked for a page past the end."
            if not response.items:
                break
            yield response
            pages_yielded += 1
            # Reachable safety net: Holman's envelope schema types
            # ``page_info`` as ``PageInfo | None``, and we've observed
            # the ``None`` case on empty queries. If a non-empty page
            # ever arrives without it, stop cleanly rather than loop
            # forever — there's no safe way to compute the next page
            # number without ``total_pages``.
            if response.page_info is None:
                break
            if page_number >= response.page_info.total_pages:
                break
            page_number += 1

        logger.debug(
            'Finished iterating %s after %d pages.',
            query.endpoint_path,
            pages_yielded,
        )

    def collect[TItem: ResponseModel](
        self,
        query: QueryInputBase[TItem],
    ) -> list[TItem]:
        """
        Fetch every page of ``query`` and return the accumulated items.

        Convenience over :meth:`iter_pages` for callers that want the
        full result set as a single list. Memory use scales with the
        number of records returned; callers who need streaming
        semantics should continue to use ``iter_pages`` directly.

        Args:
            query: The endpoint-specific query to run.

        Returns:
            A list of the concrete ``TItem`` model instances in page-
            then-record order. Empty when the query matches no records.

        Raises:
            HolmanError / TransientHolmanError / RateLimitError:
                Propagated from :meth:`iter_pages` / :meth:`send`.
        """
        return [item for page in self.iter_pages(query) for item in page.items]
