# src/pyholman/_endpoints/query_builder.py
"""
Construct an endpoint query from a validated filter model and config.

Thin adapter between the discriminated user-facing filter model (a
:class:`FrozenModel` subclass) and the transport-layer query dataclass
(a :class:`~pyholman._core.QueryInputBase` subclass). The orchestrator
calls :func:`build_query_from_filters` once per resource per run; the
public ``fetch`` entry point calls it with ``filters=None`` for
no-filter pulls.

The mapping between filter-model attributes and query-dataclass fields
relies on a naming convention — both sides share the same snake_case
attribute names. That alignment is enforced implicitly through the
``**filter_dump`` spread below: a mismatched field name raises a
``TypeError`` at construction time rather than producing a silently
wrong request.
"""

from typing import Any

from pyholman._config import ApiConfig, FleetConfig
from pyholman._core import FrozenModel, QueryInputBase, ResponseModel
from pyholman._endpoints.registry import ResourceRegistryEntry

__all__: list[str] = ['build_query_from_filters']


def build_query_from_filters(
    registry_entry: ResourceRegistryEntry,
    filters: FrozenModel | None,
    api_config: ApiConfig,
    fleet_config: FleetConfig,
) -> QueryInputBase[ResponseModel]:
    """
    Construct an endpoint query from a validated filter model and config.

    The registry entry supplies the query class; the filter model
    supplies endpoint-specific filter values; ``api_config`` supplies
    ``base_url``; ``fleet_config`` supplies ``lessee_codes``. The
    mapping from filter-model attributes to query-dataclass fields
    relies on both using the same Python attribute names by
    convention — that alignment is what makes ``**filter_dump``
    work here and is not accidental.

    ``filters`` is required-nullable rather than defaulted to ``None``
    so that a forgetful future caller fails noisily instead of silently
    producing a no-filter pull when they meant to pass a real filter
    object. Callers that genuinely want no filter overrides write
    ``filters=None`` explicitly.

    Args:
        registry_entry: Registry entry for the resource being built.
            ``registry_entry.query_class`` is the target dataclass.
        filters: Validated filter model (a
            :class:`pyholman._config.resources` variant's ``.filters``
            attribute), or ``None`` to mean "no filter overrides; the
            query carries only ``base_url`` and ``lessee_codes``, plus
            per-endpoint defaults for any optional filter fields."
            Whatever ``model_dump()`` produces (or ``{}`` for ``None``)
            is spread into the query-dataclass constructor.
        api_config: Source of ``base_url``.
        fleet_config: Source of ``lessee_codes``.

    Returns:
        A frozen ``QueryInputBase`` subclass instance ready to pass to
        :meth:`HolmanClient.send` or :meth:`HolmanClient.iter_pages`.
    """
    # ``Any`` is justified: ``model_dump()`` returns ``dict[str, Any]``
    # because filter-field value types vary across endpoints (ints,
    # tuples, datetimes, computed ints). The spread below feeds the
    # query-dataclass constructor, which is per-endpoint typed and
    # enforces the shape at call time; narrowing here would only shift
    # the same Any through a cast.
    filter_dump: dict[str, Any] = filters.model_dump() if filters is not None else {}
    return registry_entry.query_class(
        base_url=str(api_config.base_url),
        lessee_codes=fleet_config.lessee_codes,
        **filter_dump,
    )
