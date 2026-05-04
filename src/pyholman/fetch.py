# src/pyholman/fetch.py
"""
Public one-shot endpoint pulls returning a pandas DataFrame.

One public function: :func:`fetch`. Use case: a notebook or script
that wants the data for a single endpoint and nothing else — no
filters, no incremental, no disk I/O. Sibling to the YAML-driven
``Orchestrator``.

Internally fetch constructs a :class:`pyholman._client.HolmanClient`
from the four user-supplied values plus inert defaults for everything
else. No state persists between calls; each call builds its own
client and tears it down via the context manager.

Logging behavior:
    pyholman emits records through ``logging.getLogger('pyholman.*')``.
    They propagate to the root logger by default, so configuring stdlib
    logging in the calling application — e.g.,
    ``logging.basicConfig(level=logging.INFO)`` — is sufficient to
    surface them. Fetch does NOT call ``setup_logger`` and does not
    change any logging policy. Library convention is that library code
    leaves logging policy decisions to the application.
"""

import logging
from typing import Any, Final

import pandas as pd
from pydantic import SecretStr

from pyholman._client import HolmanClient
from pyholman._config import (
    ApiConfig,
    CredentialsConfig,
    FleetConfig,
    UserConfig,
)
from pyholman._core import ResponseModel
from pyholman._dataframe_tools import deduplicate_dataframe
from pyholman._endpoints.query_builder import build_query_from_filters
from pyholman._endpoints.registry import (
    EndpointName,
    ResourceRegistryEntry,
    get_registry_entry,
)

__all__: list[str] = ['fetch']

# fetch is a one-shot pull and does not iterate ``UserConfig.resources``,
# but ``UserConfig`` requires at least one resource at validation time.
# Building the one-element ``resources`` tuple from a dict and letting
# Pydantic resolve the discriminated union by name keeps fetch's
# inert-defaults helper from importing every per-endpoint
# ``*ResourceConfig`` subclass directly. Pydantic validates the dict
# against ``ResourceConfig``'s discriminator and substitutes the right
# concrete variant.
_FETCH_RESOURCES_KEY: Final[str] = 'resources'

logger: logging.Logger = logging.getLogger(__name__)


def fetch(
    endpoint: EndpointName,
    client_id: str,
    client_secret: str,
    lessee_codes: list[str],
    use_truststore: bool = False,
) -> pd.DataFrame:
    """
    Fetch every record from a single Holman endpoint and return a DataFrame.

    Programmatic one-shot pull, no disk I/O, no filters, no incremental.
    Each call is independent: a fresh :class:`HolmanClient` is built,
    every page is collected, the records are materialized, and the
    client is closed. Sibling entry point to the YAML-driven
    ``Orchestrator``.

    Args:
        endpoint: One of the registered endpoint names — see
            :data:`pyholman.EndpointName`. A name not in that set
            raises :class:`ValueError` with a message listing the
            registered names.
        client_id: Holman OAuth2 client id (the non-secret half of the
            credential pair).
        client_secret: Holman OAuth2 client secret. Wrapped in
            :class:`pydantic.SecretStr` internally so it does not
            surface in ``repr()`` or log output.
        lessee_codes: Lessee codes the calling user is authorized to
            query, including any organization id. Codes are normalized
            (uppercased, deduplicated, sorted) by the underlying
            :class:`pyholman._config.FleetConfig`.
        use_truststore: When ``True``, the HTTP transport trusts the
            host OS's certificate store via the ``truststore`` package.
            Set ``True`` on machines behind an MITM corporate proxy
            (Zscaler, etc.) presenting an internally-signed
            certificate. Defaults to ``False``.

    Returns:
        A pandas DataFrame with one row per record, columns and dtypes
        as declared by the endpoint's response model. Empty result
        sets return a zero-row DataFrame with the same typed columns.
        Byte-identical duplicate rows are dropped (matches Holman's
        habit of returning repeated records on some endpoints).

    Raises:
        ValueError: ``endpoint`` is not a registered name.
        HolmanError: 4xx responses (other than 429), unexpected
            response shapes, or any non-retryable client error.
        TransientHolmanError: 5xx responses (and network errors) that
            exhaust the retry budget.
        RateLimitError: 429 responses that exhaust the retry budget.

    Logging:
        Pyholman emits standard library log records. Configure stdlib
        logging in the calling application (e.g.,
        ``logging.basicConfig(level=logging.INFO)``) to surface them.
        Fetch does not call ``setup_logger``; that opt-in lives with
        the YAML-driven entry point.
    """
    registry_entry: ResourceRegistryEntry = get_registry_entry(endpoint)
    logger.info('Fetching endpoint %s.', registry_entry.name)

    user_config: UserConfig = _build_user_config_for_fetch(
        endpoint=endpoint,
        client_id=client_id,
        client_secret=client_secret,
        lessee_codes=lessee_codes,
        use_truststore=use_truststore,
    )

    with HolmanClient(user_config) as client:
        query = build_query_from_filters(
            registry_entry=registry_entry,
            filters=None,
            api_config=user_config.api,
            fleet_config=user_config.fleet,
        )
        records: list[ResponseModel] = client.collect(query)

    logger.debug('Collected %d record(s) from %s.', len(records), registry_entry.name)

    dataframe: pd.DataFrame = registry_entry.response_class.records_to_dataframe(
        records
    )
    dataframe = deduplicate_dataframe(dataframe)

    logger.debug(
        'Returning DataFrame with %d row(s) for %s after dedup.',
        len(dataframe),
        registry_entry.name,
    )
    return dataframe


def _build_user_config_for_fetch(
    endpoint: EndpointName,
    client_id: str,
    client_secret: str,
    lessee_codes: list[str],
    use_truststore: bool,
) -> UserConfig:
    """
    Assemble the inert-defaults UserConfig fetch needs.

    Lives here rather than as a UserConfig factory because the use
    case is fetch-specific: every section other than credentials, api,
    fleet, and the single-element ``resources`` placeholder defaults
    to the no-op shape (working directory unused, no logging policy
    override). A future caller that wants similar defaults should
    compose its own helper rather than reuse this one — sharing
    would invite drift between incidentally-similar callers.

    The single-element ``resources`` tuple is required because
    ``UserConfig.resources`` enforces ``min_length=1``. fetch does not
    iterate that tuple — it builds the query directly from the
    registry entry — but the validator needs the field populated. The
    placeholder is the requested endpoint with default filters; the
    discriminator dispatches to the right ``*ResourceConfig`` variant
    via :meth:`UserConfig.model_validate` without this helper having
    to import every variant directly.

    Args:
        endpoint: The endpoint being fetched. Used as the
            ``resources[0].name`` discriminator value.
        client_id: See :func:`fetch`.
        client_secret: See :func:`fetch`. Wrapped in ``SecretStr``
            inside.
        lessee_codes: See :func:`fetch`. Converted to a tuple before
            handing to ``FleetConfig``.
        use_truststore: See :func:`fetch`.

    Returns:
        A fully validated, frozen :class:`UserConfig`.
    """
    config_data: dict[str, Any] = {
        'credentials': CredentialsConfig(
            client_id=client_id,
            client_secret=SecretStr(client_secret),
        ),
        'api': ApiConfig(use_truststore=use_truststore),
        'fleet': FleetConfig(lessee_codes=tuple(lessee_codes)),
        _FETCH_RESOURCES_KEY: ({'name': endpoint},),
    }
    return UserConfig.model_validate(config_data)
