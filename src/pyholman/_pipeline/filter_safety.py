# src/pyholman/_pipeline/filter_safety.py
"""
Filter-model hashing and mismatch detection for incremental-refresh safety.

Two functions and one exception live here:

    - :func:`hash_filter_model` — SHA-256 digest of a filter model's
      canonicalized form. Produces what :func:`verify_filter_hash_matches`
      consumes and what :class:`~pyholman._storage.StorageMetadata`
      stamps into the sidecar.
    - :func:`verify_filter_hash_matches` — raise when the stamped
      digest on disk differs from the digest the current run produces.
    - :class:`FilterHashMismatchError` — the exception raised.

They share one concern: ensure an incremental refresh is never allowed
to mix rows written under one filter block with rows fetched under
another. Keeping the three in one module means every piece of the
check — compute, compare, raise — lives next to the others.

Why hash rather than embed the full filter dump:
    Sidecars are tiny and human-readable; a full filter dump bloats
    them (especially on endpoints with many default filter fields)
    and the dump's natural serialization order isn't guaranteed stable
    across Pydantic versions. A 64-char digest is compact, version-
    independent after canonicalization, and comparable in O(1).

Why only ``FrozenModel``:
    We hash filter models specifically. Widening the signature to any
    Pydantic model or to an opaque ``dict`` would invite callers to
    hash things whose stable-canonicalization guarantees haven't been
    thought through (computed fields? rounding? timezone handling?).
    When a second use case surfaces, a sibling function can handle it
    without loosening the constraint here.

Why this lives in ``_pipeline`` rather than ``_storage``:
    The hash itself ends up stamped into a ``StorageMetadata`` sidecar,
    but computing and verifying the hash is a per-run pipeline concern
    — :class:`ResourcePreparer` calls :func:`verify_filter_hash_matches`
    before any HTTP request, and :class:`ResourceProcessor` calls
    :func:`hash_filter_model` at persist time. Both functions are pure;
    they read and write no files. Co-locating them with the storage
    layer would couple filter validation to I/O concerns it does not
    actually share, while their pipeline-stage callers would still
    have to import them from ``_storage``.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pyholman._core import FrozenModel
from pyholman._storage import StorageMetadata

__all__: list[str] = [
    'FilterHashMismatchError',
    'hash_filter_model',
    'verify_filter_hash_matches',
]


# Number of leading hex characters surfaced in the mismatch message.
# Full 64-char digests are noise in a user-facing error; eight is
# enough to tell two digests apart at a glance without encouraging
# anyone to try to eyeball-match them.
_HASH_DISPLAY_PREFIX_LENGTH: int = 8


def hash_filter_model(filter_model: FrozenModel | None) -> str:
    """
    Return the SHA-256 hex digest of a filter model's canonical form.

    Canonicalization flow:
        1. ``model_dump(mode='json')`` — emits JSON-serializable
           primitives. Datetimes become ISO 8601 strings, tuples
           become lists; computed fields are included (Pydantic
           default), which is harmless here because filter-model
           computed fields are always pure functions of their input
           fields.
        2. ``json.dumps(..., sort_keys=True, separators=(',', ':'))``
           — alphabetical key order and no whitespace, so two
           instances with semantically identical values always
           canonicalize to the same byte sequence.
        3. SHA-256 of the UTF-8-encoded canonical JSON.

    Passing ``None`` is the documented "no filters configured" path.
    A ``None`` input hashes to the SHA-256 of ``'{}'`` — the same
    digest a freshly-constructed empty :class:`FrozenModel` would
    produce — so a snapshot resource without a filter model and an
    incremental resource that happens to have an empty filter dump
    canonicalize to the same hash. The metadata module documents this
    "always present" property; the ``None`` branch aligns the runtime
    with that contract.

    Args:
        filter_model: A :class:`FrozenModel` instance, or ``None`` to
            mean "no filter configuration." Passing a non-``FrozenModel``
            non-``None`` value is a type error and caught at the
            parameter annotation level.

    Returns:
        A 64-character lowercase hex string — the SHA-256 digest of
        the canonicalized filter model (or of ``'{}'`` for ``None``).
    """
    if filter_model is None:
        return hashlib.sha256(b'{}').hexdigest()
    dumped: dict[str, Any] = filter_model.model_dump(mode='json')
    canonical_json: str = json.dumps(dumped, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


class FilterHashMismatchError(ValueError):
    """
    Raised when the user's YAML filter block has changed since the last write.

    This is deliberately **not** a :class:`pyholman.HolmanError`. A
    ``HolmanError`` signals something went wrong with the Holman API
    or its transport; a filter-hash mismatch is entirely pyholman-
    internal — the existing sidecar was written by this library and
    the new hash was computed from the user's current YAML. The
    remediation is a configuration change, not a retry.

    The error message names the resource, the on-disk data path, the
    truncated existing and new hashes, why the run cannot proceed, and
    the concrete recovery action — so a user encountering this for the
    first time can act on it without reading source. Match the
    detail level of :class:`IncrementalStateCorruptedError` for
    consistency across pyholman's pipeline-internal exceptions.

    Vocabulary: the values are referred to as ``existing_hash`` and
    ``new_hash`` everywhere — attribute names, docstrings, and the
    rendered message. ``hash`` (the noun) matches the attribute
    suffix on :class:`StorageMetadata.filters_hash` and the function
    :func:`hash_filter_model`; ``existing`` and ``new`` describe
    "already stored on disk" and "computed for this run" without
    introducing a second word pair to translate between.

    Attributes:
        resource_name: Registered resource name whose filter hash
            failed to match (e.g., ``'contacts'``).
        data_path: Absolute path to the on-disk data file written
            under the prior filter configuration. Bundled with the
            resource directory containing the metadata sidecar; the
            recovery action targets ``data_path.parent``.
        existing_hash: The hash already stored in the sidecar.
        new_hash: The hash pyholman computed for the current run.
    """

    def __init__(
        self,
        *,
        resource_name: str,
        data_path: Path,
        existing_hash: str,
        new_hash: str,
    ) -> None:
        self.resource_name: str = resource_name
        self.data_path: Path = data_path
        self.existing_hash: str = existing_hash
        self.new_hash: str = new_hash
        super().__init__(
            f'Filter configuration for resource {resource_name!r} has '
            f'changed since the last successful run '
            f'(existing hash {existing_hash[:_HASH_DISPLAY_PREFIX_LENGTH]}..., '
            f'new hash {new_hash[:_HASH_DISPLAY_PREFIX_LENGTH]}...). '
            f'The on-disk data at {data_path} reflects the prior filter '
            f'configuration; continuing with the new configuration would '
            f'silently mix two filter regimes and produce a dataset that is '
            f'internally inconsistent. To proceed, either revert the filter '
            f'change to match the prior run, or delete or rename '
            f'{data_path.parent} to force a fresh bootstrap on the next run.'
        )


def verify_filter_hash_matches(
    existing_metadata: StorageMetadata,
    new_filter_hash: str,
    *,
    data_path: Path,
) -> None:
    """
    Raise if the existing sidecar's filter hash differs from the new one.

    Args:
        existing_metadata: Sidecar loaded from the resource directory
            before the orchestrator starts writing. Carries the
            resource name (``existing_metadata.endpoint``) which is
            stamped into the error so a user reading a multi-resource
            log can tell which resource failed.
        new_filter_hash: Hash of the filter model the current run will
            use, produced by :func:`hash_filter_model`.
        data_path: Absolute path to the on-disk data file. Stamped
            into the raised error so the user has the concrete path
            to act on for recovery — its parent directory is the
            resource directory the user is told to delete or rename.

    Returns:
        None. Silent when the hashes match.

    Raises:
        FilterHashMismatchError: If the hashes differ.
    """
    if existing_metadata.filters_hash == new_filter_hash:
        return
    raise FilterHashMismatchError(
        resource_name=existing_metadata.endpoint,
        data_path=data_path,
        existing_hash=existing_metadata.filters_hash,
        new_hash=new_filter_hash,
    )
