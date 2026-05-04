# tests/_pipeline/test_bundle.py
"""Smoke tests for :class:`ResourceBundle` field defaults and slot enforcement."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyholman._config import OutputConfig, OutputFormat, ParquetCompression, UserConfig
from pyholman._config.resources import VehiclesResourceConfig
from pyholman._endpoints.registry import get_registry_entry
from pyholman._endpoints.vehicles import VehiclesFilters
from pyholman._pipeline import ResourceBundle
from pyholman._storage import get_storage_handler

__all__: list[str] = []


_INSTANT: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


def _build_user_config(tmp_path: Path) -> UserConfig:
    return UserConfig.model_validate(
        {
            'credentials': {
                'client_id': 'my-client-id',
                'client_secret': 'test-secret-value',
            },
            'api': {'base_url': 'https://api.holman.solutions'},
            'fleet': {'lessee_codes': ['ABCD']},
            'working_directory': tmp_path,
            'resources': [{'name': 'vehicles'}],
        }
    )


def _build_minimal_bundle(tmp_path: Path) -> ResourceBundle:
    user_config: UserConfig = _build_user_config(tmp_path)
    return ResourceBundle(
        resource_name='vehicles',
        resource_config=VehiclesResourceConfig(
            name='vehicles',
            incremental=False,
            filters=VehiclesFilters(),
        ),
        registry_entry=get_registry_entry('vehicles'),
        storage_handler=get_storage_handler(
            output_config=OutputConfig(
                format=OutputFormat.PARQUET,
                compression=ParquetCompression.SNAPPY,
            ),
            working_directory=tmp_path,
            resource_name='vehicles',
        ),
        user_config=user_config,
        is_incremental=False,
        is_incremental_with_prior=False,
        window_start=None,
    )


class TestResourceBundleDefaults:
    def test_optional_fields_default_to_none(self, tmp_path: Path) -> None:
        bundle: ResourceBundle = _build_minimal_bundle(tmp_path)
        assert bundle.started_at_utc is None
        assert bundle.query is None
        assert bundle.records is None
        assert bundle.dataframe is None


class TestResourceBundleSlots:
    def test_unknown_attribute_raises_attribute_error(self, tmp_path: Path) -> None:
        # ``slots=True`` means assignments to undeclared attributes
        # raise ``AttributeError``. Pinning this matters because the
        # bundle is the pipeline's only mutable carrier — typo-driven
        # state leakage through ``self._bundle.<misspelled>`` would
        # corrupt subsequent pipeline stages silently otherwise.
        bundle: ResourceBundle = _build_minimal_bundle(tmp_path)
        with pytest.raises(AttributeError):
            bundle.bogus_attribute = 'oops'  # type: ignore[attr-defined]

    def test_declared_attributes_are_mutable(self, tmp_path: Path) -> None:
        bundle: ResourceBundle = _build_minimal_bundle(tmp_path)
        # A pipeline stage replaces ``window_start`` after the builder
        # set it — the dataclass is mutable by design.
        new_window: datetime = _INSTANT
        bundle.window_start = new_window
        assert bundle.window_start == new_window
