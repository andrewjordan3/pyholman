# tests/test_filter_safety.py
"""Tests for ``hash_filter_model``, ``verify_filter_hash_matches``, and ``FilterHashMismatchError``."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyholman import HolmanError
from pyholman._config import OutputFormat, ParquetCompression
from pyholman._endpoints.engine_hours import EngineHoursFilters
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrderFilters,
)
from pyholman._endpoints.odometer import OdometerFilters
from pyholman._endpoints.vehicles import VehiclesFilters
from pyholman._pipeline import (
    FilterHashMismatchError,
    hash_filter_model,
    verify_filter_hash_matches,
)
from pyholman._storage import StorageMetadata, StorageRunMode

__all__: list[str] = []


# =============================================================================
# hash_filter_model
# =============================================================================

_HEX64_PATTERN: re.Pattern[str] = re.compile(r'[0-9a-f]{64}')


# Known-value regression anchor. If the canonicalization path ever
# changes — field order, default-value handling, datetime serialization
# — these digests change and the tests fail loudly rather than silently
# invalidating every sidecar on disk.
_KNOWN_EMPTY_OBJECT_HASH: str = (
    '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'
)


class TestHashShape:
    def test_empty_filter_returns_64_lowercase_hex(self) -> None:
        digest: str = hash_filter_model(OdometerFilters())
        assert _HEX64_PATTERN.fullmatch(digest) is not None

    def test_populated_filter_returns_64_lowercase_hex(self) -> None:
        digest: str = hash_filter_model(VehiclesFilters(status_codes=(1, 2)))
        assert _HEX64_PATTERN.fullmatch(digest) is not None


class TestDeterminism:
    def test_same_instance_twice_yields_same_hash(self) -> None:
        instance: VehiclesFilters = VehiclesFilters(status_codes=(1,))
        assert hash_filter_model(instance) == hash_filter_model(instance)

    def test_two_instances_same_values_same_hash(self) -> None:
        first: VehiclesFilters = VehiclesFilters(status_codes=(1, 2))
        second: VehiclesFilters = VehiclesFilters(status_codes=(1, 2))
        assert hash_filter_model(first) == hash_filter_model(second)

    def test_different_tuple_orders_hash_differently(self) -> None:
        # The tuple is order-bearing on the wire (Holman serializes as
        # a comma-joined list in declaration order), so the hash
        # reflects that.
        forward: VehiclesFilters = VehiclesFilters(status_codes=(1, 2))
        reverse: VehiclesFilters = VehiclesFilters(status_codes=(2, 1))
        assert hash_filter_model(forward) != hash_filter_model(reverse)


class TestDifferentiation:
    def test_different_filter_classes_produce_different_hashes(self) -> None:
        empty_odometer: str = hash_filter_model(OdometerFilters())
        empty_engine: str = hash_filter_model(EngineHoursFilters())
        empty_vehicles: str = hash_filter_model(VehiclesFilters())
        # Odometer and engine hours both have zero declared fields, so
        # they canonicalize to the same ``{}``; vehicles has
        # ``status_codes``, ``last_change_date``, and the computed
        # ``sold_date_code`` in its dump.
        assert empty_odometer == empty_engine
        assert empty_vehicles != empty_odometer

    def test_different_values_produce_different_hashes(self) -> None:
        no_filter: str = hash_filter_model(VehiclesFilters())
        with_filter: str = hash_filter_model(VehiclesFilters(status_codes=(1,)))
        assert no_filter != with_filter

    def test_empty_versus_empty_of_same_class(self) -> None:
        first: OdometerFilters = OdometerFilters()
        second: OdometerFilters = OdometerFilters()
        assert hash_filter_model(first) == hash_filter_model(second)


class TestCrossClassEquivalence:
    def test_structurally_equivalent_empty_filters_hash_identically(
        self,
    ) -> None:
        # Odometer, engine hours, and maintenance-PO empty filters all
        # serialize to identical JSON shapes (empty dict for the first
        # two; ``{"last_change_date": null}`` for the third). Odometer
        # and engine hours should match; maintenance should differ.
        assert hash_filter_model(OdometerFilters()) == hash_filter_model(
            EngineHoursFilters()
        )
        assert hash_filter_model(OdometerFilters()) != hash_filter_model(
            MaintenancePurchaseOrderFilters()
        )


class TestKnownValueRegression:
    def test_empty_odometer_filter_hash_is_known(self) -> None:
        # The SHA-256 of ``{}`` is a fixed 64-char hex. Empty
        # ``FrozenModel`` subclasses with no declared fields all
        # canonicalize to that same digest.
        assert hash_filter_model(OdometerFilters()) == _KNOWN_EMPTY_OBJECT_HASH

    def test_none_filter_hashes_to_empty_object_digest(self) -> None:
        # ``None`` is the documented "no filters configured" path. It
        # must produce the same digest as a freshly-constructed empty
        # ``FrozenModel`` so a snapshot resource without filters and
        # an incremental resource with no filters declared canonicalize
        # to the same hash. Pinned against the literal SHA-256 of
        # ``b'{}'``.
        assert hash_filter_model(None) == _KNOWN_EMPTY_OBJECT_HASH
        assert hash_filter_model(None) == hash_filter_model(OdometerFilters())

    def test_datetime_filter_canonicalizes_as_iso(self) -> None:
        # Regression guard for ``mode='json'``: datetimes round-trip as
        # ISO strings, so the digest stays stable across the pydantic
        # datetime / ISO-string representation choice.
        instant: datetime = datetime(2026, 4, 20, 14, 30, 45, tzinfo=UTC)
        first_hash: str = hash_filter_model(
            MaintenancePurchaseOrderFilters(last_change_date=instant)
        )
        second_hash: str = hash_filter_model(
            MaintenancePurchaseOrderFilters(last_change_date=instant)
        )
        assert first_hash == second_hash
        assert _HEX64_PATTERN.fullmatch(first_hash) is not None


# =============================================================================
# verify_filter_hash_matches / FilterHashMismatchError
# =============================================================================

_HASH_A: str = '0' * 64
_HASH_B: str = 'f' * 64
# Standin path the tests pass to ``verify_filter_hash_matches``. The
# function only stamps it into the raised exception; it never reads
# from disk, so the path does not need to exist.
_TEST_DATA_PATH: Path = Path('/var/data/pyholman/vehicles/vehicles.parquet')


def _make_metadata(filters_hash: str) -> StorageMetadata:
    instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    return StorageMetadata(
        endpoint='vehicles',
        pyholman_version='0.1.0',
        run_mode=StorageRunMode.FULL_REFRESH,
        run_started_utc=instant,
        run_completed_utc=instant,
        most_recent_record_utc=None,
        record_count=0,
        output_format=OutputFormat.PARQUET,
        compression=ParquetCompression.SNAPPY,
        filters_hash=filters_hash,
    )


class TestMatchingHashes:
    def test_returns_none(self) -> None:
        metadata: StorageMetadata = _make_metadata(_HASH_A)
        result = verify_filter_hash_matches(
            metadata, _HASH_A, data_path=_TEST_DATA_PATH,
        )
        assert result is None


class TestMismatchedHashes:
    def test_raises_filter_hash_mismatch_error(self) -> None:
        metadata: StorageMetadata = _make_metadata(_HASH_A)
        with pytest.raises(FilterHashMismatchError):
            verify_filter_hash_matches(
                metadata, _HASH_B, data_path=_TEST_DATA_PATH,
            )

    def test_exception_carries_resource_path_and_hashes(self) -> None:
        metadata: StorageMetadata = _make_metadata(_HASH_A)
        with pytest.raises(FilterHashMismatchError) as caught:
            verify_filter_hash_matches(
                metadata, _HASH_B, data_path=_TEST_DATA_PATH,
            )
        # ``resource_name`` flows through from
        # ``StorageMetadata.endpoint`` so a multi-resource caller can
        # tell which resource failed without parsing the message.
        assert caught.value.resource_name == 'vehicles'
        assert caught.value.data_path == _TEST_DATA_PATH
        assert caught.value.existing_hash == _HASH_A
        assert caught.value.new_hash == _HASH_B

    def test_exception_message_names_resource_path_and_hashes(self) -> None:
        metadata: StorageMetadata = _make_metadata(_HASH_A)
        with pytest.raises(FilterHashMismatchError) as caught:
            verify_filter_hash_matches(
                metadata, _HASH_B, data_path=_TEST_DATA_PATH,
            )
        message: str = str(caught.value)
        # Resource and path appear verbatim so a user can grep for
        # either.
        assert "'vehicles'" in message
        assert str(_TEST_DATA_PATH) in message
        # Hash fingerprints are abbreviated to the leading prefix and
        # labeled with the same vocabulary the attribute names use —
        # ``existing_hash`` / ``new_hash`` rather than the previous
        # mismatched ``prior digest`` / ``current digest`` phrasing.
        assert f'existing hash {_HASH_A[:8]}' in message
        assert f'new hash {_HASH_B[:8]}' in message

    def test_exception_message_describes_what_changed_and_recovery(
        self,
    ) -> None:
        # Substance check: the message explains why the run cannot
        # proceed and gives a concrete recovery action that targets
        # the resource directory (the parent of the data file).
        metadata: StorageMetadata = _make_metadata(_HASH_A)
        with pytest.raises(FilterHashMismatchError) as caught:
            verify_filter_hash_matches(
                metadata, _HASH_B, data_path=_TEST_DATA_PATH,
            )
        message: str = str(caught.value)
        # What changed.
        assert 'Filter configuration' in message
        assert 'changed' in message
        # Why it matters.
        assert 'mix' in message  # "would silently mix two filter regimes"
        # How to recover — "delete or rename" the resource directory.
        assert 'delete' in message
        assert 'rename' in message
        assert str(_TEST_DATA_PATH.parent) in message


class TestExceptionType:
    def test_is_value_error_subclass(self) -> None:
        assert issubclass(FilterHashMismatchError, ValueError)

    def test_is_not_holman_error_subclass(self) -> None:
        # A filter-hash mismatch is a pyholman-vs-pyholman concern; the
        # Holman API did not cause it. Mistakenly subclassing
        # ``HolmanError`` would collapse distinct error categories the
        # transport layer's retry/raise policy cares about.
        assert not issubclass(FilterHashMismatchError, HolmanError)
