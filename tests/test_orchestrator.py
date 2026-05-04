# tests/test_orchestrator.py
"""Tests for :class:`pyholman.Orchestrator`."""

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

import httpx
import pandas as pd
import pytest
from pydantic import ValidationError

from pyholman import HolmanError, Orchestrator, orchestrator as orchestrator_module
from pyholman._clock import FrozenClock, SystemClock
from pyholman._config import OutputFormat, ParquetCompression
from pyholman._core.constants import PACKAGE_NAME
from pyholman._endpoints.vehicles import Vehicle, VehiclesFilters
from pyholman._pipeline import FilterHashMismatchError, hash_filter_model
from pyholman._storage import (
    ParquetHandler,
    StorageMetadata,
    StorageRunMode,
)
from pyholman._storage.metadata import get_pyholman_version
from tests._helpers.http import (
    _install_mock_transport,
    _page_body,
    _RecordingHandler,
)

__all__: list[str] = []


# =============================================================================
# Constants and YAML helpers
# =============================================================================


_TOKEN_ENDPOINT_PATH: str = '/sso/sts/connect/token'
_VEHICLES_ENDPOINT_PATH: str = '/CustomerDataAPI/vehicles/basic-query'
_ODOMETER_ENDPOINT_PATH: str = '/CustomerDataAPI/odometer/basic-query'
_CONTACTS_ENDPOINT_PATH: str = '/CustomerDataAPI/contacts/basic-query'

_TOKEN_RESPONSE_BODY: bytes = (
    b'{"access_token":"test-token",'
    b'"token_type":"Bearer",'
    b'"expires_in":3600,'
    b'"scope":"read"}'
)


def _always_token_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=_TOKEN_RESPONSE_BODY)


def _vehicle_item(
    holman_vehicle_number: str,
    *,
    last_change_date: datetime | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {'holmanVehicleNumber': holman_vehicle_number}
    if last_change_date is not None:
        item['lastChangeDate'] = last_change_date.isoformat()
    return item


def _odometer_item(holman_vehicle_number: str) -> dict[str, object]:
    return {'holmanVehicleNumber': holman_vehicle_number}


def _contact_item(
    contact_id: str,
    *,
    last_change_date: datetime | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {'contactId': contact_id}
    if last_change_date is not None:
        item['lastChangeDate'] = last_change_date.isoformat()
    return item


_YAML_BODY_TEMPLATE: str = dedent(
    """\
    credentials:
      client_id: 'my-client-id'
    api:
      base_url: 'https://api.holman.solutions'
    fleet:
      organization_id: 'ORG1'
      lessee_codes:
        - 'ABCD'
    working_directory: '{working_directory}'
    {extra_sections}
    resources:
    {resources}
    """
)


def _write_config(
    tmp_path: Path,
    *,
    resources_yaml: str,
    extra_sections: str = '',
) -> Path:
    """Write a valid YAML config; return its path."""
    body: str = _YAML_BODY_TEMPLATE.format(
        working_directory=tmp_path / 'data',
        extra_sections=extra_sections,
        resources=resources_yaml,
    )
    config_path: Path = tmp_path / 'config.yaml'
    config_path.write_text(body)
    return config_path


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def silenced_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity's retry waits instantaneous."""

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(time, 'sleep', _no_sleep)


@pytest.fixture
def quiet_setup_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Replace ``setup_logger`` with a no-op so caplog can capture
    pyholman log records.

    The real ``setup_logger`` sets ``pyholman.propagate = False`` and
    replaces handlers, both of which prevent caplog (which sits on the
    root logger by default) from observing pyholman output. Tests that
    only need to assert behavior — not logging policy — patch this
    fixture in to keep the propagation chain intact. The fixture also
    resets ``pyholman.propagate`` to ``True`` because earlier tests
    that run the real ``setup_logger`` would otherwise leave the
    module-level logger with ``propagate=False``.
    """

    def _no_op(_config: object) -> None:
        return None

    monkeypatch.setattr(orchestrator_module, 'setup_logger', _no_op)
    package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
    monkeypatch.setattr(package_logger, 'propagate', True)


def _seed_metadata(
    *,
    config_path: Path,
    resource_name: str,
    most_recent_record_utc: datetime,
    filters_hash: str,
    record_count: int = 1,
) -> None:
    """Write a valid metadata sidecar at the resource directory."""
    config_yaml: str = config_path.read_text()
    # Pull working_directory out of the rendered YAML so this helper
    # does not need to know its derivation.
    for line in config_yaml.splitlines():
        if line.startswith('working_directory:'):
            working_directory: Path = Path(line.split(':', 1)[1].strip().strip("'"))
            break
    else:
        raise AssertionError('working_directory not found in YAML')

    handler: ParquetHandler = ParquetHandler(
        working_directory=working_directory,
        resource_name=resource_name,
    )
    handler.write_metadata(
        StorageMetadata(
            endpoint=resource_name,
            pyholman_version=get_pyholman_version(),
            run_mode=StorageRunMode.INCREMENTAL,
            run_started_utc=most_recent_record_utc,
            run_completed_utc=most_recent_record_utc,
            most_recent_record_utc=most_recent_record_utc,
            record_count=record_count,
            output_format=OutputFormat.PARQUET,
            compression=ParquetCompression.SNAPPY,
            filters_hash=filters_hash,
        )
    )


def _build_handler(
    path_to_response: dict[str, Callable[[httpx.Request], httpx.Response]],
) -> _RecordingHandler:
    """Wire token and per-resource responders into a single handler."""
    return _RecordingHandler(
        {_TOKEN_ENDPOINT_PATH: _always_token_response, **path_to_response}
    )


# =============================================================================
# Construction
# =============================================================================


class TestConstruction:
    def test_loads_yaml_and_configures_logger(self, tmp_path: Path) -> None:
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n',
        )

        orchestrator: Orchestrator = Orchestrator(config_path=config_path)

        assert len(orchestrator._user_config.resources) == 1
        assert isinstance(orchestrator._clock, SystemClock)
        # ``setup_logger`` flips propagate off and installs a console
        # handler; both are observable on the package logger.
        package_logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
        assert package_logger.propagate is False
        assert len(package_logger.handlers) >= 1

    def test_missing_path_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Orchestrator(config_path=tmp_path / 'does_not_exist.yaml')

    def test_missing_secret_raises_runtime_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv('HOLMAN_CLIENT_SECRET', raising=False)
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n',
        )

        with pytest.raises(RuntimeError, match='HOLMAN_CLIENT_SECRET'):
            Orchestrator(config_path=config_path)

    def test_unknown_resource_name_raises_validation_error(
        self,
        tmp_path: Path,
    ) -> None:
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: bogus_resource\n',
        )
        with pytest.raises(ValidationError):
            Orchestrator(config_path=config_path)


# =============================================================================
# run() — single-resource happy paths
# =============================================================================


class TestSingleResourceFullRefresh:
    def test_writes_data_and_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1'), _odometer_item('V2')],
                        total_count=2,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        Orchestrator(config_path=config_path).run()

        # Snapshot path → for_snapshot factory → most_recent_record_utc=None.
        odometer_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='odometer',
        )
        assert odometer_handler.data_path.exists()
        metadata: StorageMetadata | None = odometer_handler.read_metadata()
        assert metadata is not None
        assert metadata.run_mode == StorageRunMode.FULL_REFRESH
        assert metadata.most_recent_record_utc is None
        assert metadata.record_count == 2


class TestSingleResourceIncrementalNoPrior:
    def test_first_time_incremental_stamps_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        Orchestrator(config_path=config_path).run()

        vehicles_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        metadata: StorageMetadata | None = vehicles_handler.read_metadata()
        assert metadata is not None
        # Run mode reflects configuration — INCREMENTAL even on a
        # first-time pull that effectively writes a full snapshot.
        assert metadata.run_mode == StorageRunMode.INCREMENTAL
        assert metadata.most_recent_record_utc == record_instant
        # Filter hash matches the empty-default ``VehiclesFilters``.
        assert metadata.filters_hash == hash_filter_model(VehiclesFilters())


class TestSingleResourceIncrementalWithPrior:
    def test_merge_combines_prior_and_new_rows(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )

        # Seed prior data and metadata so the run is incremental-with-prior.
        # ``V_OLD`` is well before the resolved window so the merge keeps
        # it; ``V_RECENT`` was the prior run's newest record and is
        # inside the resolved window so the merge replaces it with the
        # freshly fetched ``V_NEW``.
        very_old_record_utc: datetime = datetime(2024, 1, 1, tzinfo=UTC)
        prior_most_recent_utc: datetime = datetime(2026, 1, 1, tzinfo=UTC)

        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': very_old_record_utc.isoformat(),
                        }
                    ),
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_RECENT',
                            'lastChangeDate': prior_most_recent_utc.isoformat(),
                        }
                    ),
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_most_recent_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
            record_count=2,
        )

        new_record_utc: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=new_record_utc)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        Orchestrator(config_path=config_path).run()

        # Both records survive: V_OLD (outside the resolved window) +
        # V_NEW (inside).
        merged: pd.DataFrame = prior_handler.to_dataframe()
        assert set(merged['holman_vehicle_number'].tolist()) == {'V_OLD', 'V_NEW'}


# =============================================================================
# run() — multi-resource ordering and fail-fast
# =============================================================================


class TestMultiResource:
    def test_declaration_order_honored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '  - name: odometer\n'
                '  - name: contacts\n'
                '    incremental: true\n'
            ),
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
                _CONTACTS_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_contact_item('C1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        # All three data files exist.
        for resource_name in ('vehicles', 'odometer', 'contacts'):
            assert (tmp_path / 'data' / resource_name).is_dir()

        # The "Starting resource" lines appeared in declaration order.
        starting_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith('Starting resource')
        ]
        assert starting_lines == [
            'Starting resource vehicles',
            'Starting resource odometer',
            'Starting resource contacts',
        ]

    def test_per_resource_fail_fast(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del silenced_sleep, quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '  - name: odometer\n'
                '  - name: contacts\n'
                '    incremental: true\n'
            ),
            extra_sections='retry:\n  max_attempts: 1\n',
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
                # Odometer fails with a non-retryable 401 — propagates as
                # ``HolmanError`` and stops the run.
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    401, content=b'unauthorized'
                ),
                # Contacts is wired but should never be called.
                _CONTACTS_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_contact_item('C1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with (
            caplog.at_level(logging.ERROR, logger=PACKAGE_NAME),
            pytest.raises(HolmanError),
        ):
            Orchestrator(config_path=config_path).run()

        # Resource 1 (vehicles) completed persist; its data file exists.
        assert (tmp_path / 'data' / 'vehicles' / 'vehicles.parquet').exists()
        # Resource 3 (contacts) was never attempted.
        assert not (tmp_path / 'data' / 'contacts').exists()
        # Contacts handler was never called either.
        assert handler.requests_for_path(_CONTACTS_ENDPOINT_PATH) == []

        # The ERROR log line names the failing resource.
        error_messages: list[str] = [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.ERROR
        ]
        assert any('odometer' in message for message in error_messages)


# =============================================================================
# run() — hash mismatch fails before any HTTP request
# =============================================================================


class TestHashMismatch:
    def test_hash_mismatch_raises_before_api_call(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )
        # Seed prior metadata with a digest that cannot match the
        # default empty-filter digest.
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=datetime(2026, 4, 1, tzinfo=UTC),
            filters_hash='f' * 64,
        )
        # Seed an empty data file so to_dataframe (if it were ever
        # called) would not FileNotFoundError. We expect it never runs.
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V1',
                            'lastChangeDate': '2026-04-01T00:00:00+00:00',
                        }
                    )
                ]
            )
        )

        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: pytest.fail(
                    'vehicles endpoint must not be hit on hash-mismatch'
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with pytest.raises(FilterHashMismatchError) as caught:
            Orchestrator(config_path=config_path).run()

        # End-to-end: the error reaching the orchestrator's caller
        # carries the structured attributes and a message a user can
        # act on without reading source. The structured attributes
        # name the resource and the on-disk data file; the message
        # echoes those plus the recovery (delete or rename the
        # resource directory).
        assert caught.value.resource_name == 'vehicles'
        expected_data_path: Path = tmp_path / 'data' / 'vehicles' / 'vehicles.parquet'
        assert caught.value.data_path == expected_data_path
        message: str = str(caught.value)
        assert "'vehicles'" in message
        assert str(expected_data_path) in message
        assert str(expected_data_path.parent) in message
        assert 'delete' in message
        assert 'rename' in message

        # The vehicles endpoint was never called.
        assert handler.requests_for_path(_VEHICLES_ENDPOINT_PATH) == []
        # No OAuth token request either — the prepare phase runs
        # before the HolmanClient context opens.
        assert handler.requests_for_path(_TOKEN_ENDPOINT_PATH) == []


# =============================================================================
# run() — empty results raise at persist
# =============================================================================


class TestEmptyResults:
    def test_zero_records_raise_at_persist(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )
        # Holman returns an empty page (no items, no pageInfo) — first
        # iter_pages call yields nothing, collect returns [].
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[],
                        total_count=0,
                        total_pages=None,
                        message='No data found.',
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with pytest.raises(ValueError, match='empty'):
            Orchestrator(config_path=config_path).run()


# =============================================================================
# run() — repeated invocations
# =============================================================================


class TestMultipleRunsSameInstance:
    def test_second_run_writes_second_payload(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )

        first_payload: list[dict[str, object]] = [_odometer_item('V1')]
        second_payload: list[dict[str, object]] = [
            _odometer_item('V2'),
            _odometer_item('V3'),
        ]
        active_payload: list[list[dict[str, object]]] = [first_payload]

        def _odometer_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page_body(
                    items=active_payload[0],
                    total_count=len(active_payload[0]),
                    total_pages=1,
                ),
            )

        handler: _RecordingHandler = _build_handler(
            {_ODOMETER_ENDPOINT_PATH: _odometer_handler}
        )
        _install_mock_transport(monkeypatch, handler)

        orchestrator: Orchestrator = Orchestrator(config_path=config_path)
        orchestrator.run()

        # Swap to the second payload and run again on the same instance.
        active_payload[0] = second_payload
        orchestrator.run()

        # The data file reflects the second run.
        odometer_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='odometer',
        )
        restored: pd.DataFrame = odometer_handler.to_dataframe()
        assert restored['holman_vehicle_number'].tolist() == ['V2', 'V3']


# =============================================================================
# Logging — total-run timing line
# =============================================================================


class TestRunCompletionLog:
    def test_completed_line_emitted_after_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        completion_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if 'Completed all' in record.getMessage()
        ]
        assert len(completion_lines) == 1
        assert '1 resources' in completion_lines[0]


# =============================================================================
# Per-resource timing and disambiguating log labels
# =============================================================================


_RESOURCE_ELAPSED_PATTERN: re.Pattern[str] = re.compile(
    r'^Wrote (?P<resource>\S+): \d+ records to .* '
    r'\(resource elapsed: (?P<elapsed>\d+\.\d{2})s\)$'
)
_RUN_ELAPSED_PATTERN: re.Pattern[str] = re.compile(
    r'^Completed all \d+ resources \(run elapsed: (?P<elapsed>\d+\.\d{2})s\)$'
)


class TestPerResourceTiming:
    """
    The per-resource log line measures only that resource's processing
    time, not the cumulative wall-clock since the run began. Before the
    fix, a resource's stopwatch was started at builder time (all bundles
    are built up-front before processing begins), so a resource
    processed second reported (its elapsed) + (every prior resource's
    elapsed) — odometer's ~14 wall-clock seconds was logged as ~27s.
    """

    @staticmethod
    def _orchestrator_with_frozen_clock(
        config_path: Path,
        clock: FrozenClock,
    ) -> Orchestrator:
        # Construct via the public surface, then swap the clock. The
        # orchestrator owns ``_clock`` in its slots, so reassignment
        # works; this mirrors the controlled-time idiom used elsewhere
        # in the test suite.
        orchestrator: Orchestrator = Orchestrator(config_path=config_path)
        orchestrator._clock = clock
        return orchestrator

    def test_resource_elapsed_isolated_from_other_resources(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Reproducible-time scheme: the HTTP mock handler advances a
        # FrozenClock by a known, per-resource amount when the
        # corresponding API endpoint is called. The orchestrator
        # captures its run and per-resource stopwatches against that
        # same clock, so the reported elapsed values are deterministic
        # functions of the advances injected during processing.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '  - name: odometer\n'
            ),
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        clock: FrozenClock = FrozenClock(start_time_utc=record_instant)

        # Real-world scenario: vehicles is slow (10s), odometer is fast
        # (3s). Before the fix, odometer's reported elapsed would be
        # ~13s (wrongly including the vehicles work). After the fix,
        # each resource's elapsed reflects only its own processing.
        vehicles_call_count: int = 0
        odometer_call_count: int = 0

        def _vehicles_response(_request: httpx.Request) -> httpx.Response:
            nonlocal vehicles_call_count
            vehicles_call_count += 1
            clock.advance(timedelta(seconds=10))
            return httpx.Response(
                200,
                content=_page_body(
                    items=[_vehicle_item('V1', last_change_date=record_instant)],
                    total_count=1,
                    total_pages=1,
                ),
            )

        def _odometer_response(_request: httpx.Request) -> httpx.Response:
            nonlocal odometer_call_count
            odometer_call_count += 1
            clock.advance(timedelta(seconds=3))
            return httpx.Response(
                200,
                content=_page_body(
                    items=[_odometer_item('V1')],
                    total_count=1,
                    total_pages=1,
                ),
            )

        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: _vehicles_response,
                _ODOMETER_ENDPOINT_PATH: _odometer_response,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        orchestrator: Orchestrator = self._orchestrator_with_frozen_clock(
            config_path=config_path,
            clock=clock,
        )
        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            orchestrator.run()

        # Index the per-resource elapsed values keyed by resource name.
        per_resource_elapsed: dict[str, float] = {}
        for record in caplog.records:
            match: re.Match[str] | None = _RESOURCE_ELAPSED_PATTERN.match(
                record.getMessage()
            )
            if match is not None:
                per_resource_elapsed[match.group('resource')] = float(
                    match.group('elapsed')
                )
        assert set(per_resource_elapsed) == {'vehicles', 'odometer'}
        # Each resource's reported elapsed is bounded by its own
        # injected advance — odometer's 3s advance cannot leak into
        # vehicles' line, and vehicles' 10s advance cannot leak into
        # odometer's line. A small tolerance accommodates any
        # additional ``monotonic_seconds()`` calls the framework makes.
        assert 10.0 <= per_resource_elapsed['vehicles'] < 13.0
        assert 3.0 <= per_resource_elapsed['odometer'] < 6.0

    def test_per_resource_and_run_log_lines_use_disambiguating_labels(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # A reader of the log must be able to tell which timer
        # corresponds to which line without cross-referencing
        # timestamps. Pin both labels here.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        messages: list[str] = [record.getMessage() for record in caplog.records]
        resource_lines: list[str] = [
            message for message in messages if _RESOURCE_ELAPSED_PATTERN.match(message)
        ]
        run_lines: list[str] = [
            message for message in messages if _RUN_ELAPSED_PATTERN.match(message)
        ]
        assert len(resource_lines) == 1
        assert len(run_lines) == 1
        assert 'resource elapsed:' in resource_lines[0]
        assert 'run elapsed:' in run_lines[0]


# =============================================================================
# Bootstrap announcement for first-time incremental
# =============================================================================


_BOOTSTRAP_LINE_PATTERN: re.Pattern[str] = re.compile(
    r"^Resource '\S+': no existing metadata found; performing bootstrap "
    r'load for incremental resource\.$'
)


class TestBootstrapAnnouncement:
    """
    A resource configured ``incremental: true`` with no prior metadata
    silently does a full pull on first run. Without an explicit log
    line a reader cannot distinguish a bootstrap run from a
    steady-state incremental until they notice the metadata sidecar
    is fresh — a subtle signal that does not survive a busy log.
    """

    def test_first_time_incremental_emits_bootstrap_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        bootstrap_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _BOOTSTRAP_LINE_PATTERN.match(record.getMessage())
        ]
        assert len(bootstrap_lines) == 1
        assert "'vehicles'" in bootstrap_lines[0]

    def test_steady_state_incremental_does_not_emit_bootstrap_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
        )
        # Seed prior data + metadata so this run is incremental-with-prior.
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_record_utc: datetime = datetime(2026, 1, 1, tzinfo=UTC)
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )

        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        bootstrap_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _BOOTSTRAP_LINE_PATTERN.match(record.getMessage())
        ]
        assert bootstrap_lines == []

    def test_snapshot_resource_does_not_emit_bootstrap_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Snapshot resources are not incremental, so the bootstrap
        # branch must not light up for them either.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        bootstrap_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _BOOTSTRAP_LINE_PATTERN.match(record.getMessage())
        ]
        assert bootstrap_lines == []


# =============================================================================
# Per-resource configured-filters and resolved-query log lines
# =============================================================================


_CONFIGURED_FILTERS_PATTERN: re.Pattern[str] = re.compile(
    r"^Resource '(?P<resource>[^']+)' configured filters: (?P<rendering>.*)$"
)
_RESOLVED_QUERY_PATTERN: re.Pattern[str] = re.compile(
    r"^Resource '(?P<resource>[^']+)' resolved query parameters: "
    r'(?P<rendering>.*)$'
)


class TestConfiguredFiltersLog:
    """
    Each per-resource processing iteration emits an INFO line showing
    what the user actually configured under ``filters:``. Without this
    line a reader cannot tell whether their YAML filter block was read
    at all, much less whether it survived window resolution.
    """

    def test_resource_with_no_filters_logs_none_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        # Snapshot resource (odometer) with no ``filters`` block.
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        configured_lines: list[tuple[str, str]] = [
            (match.group('resource'), match.group('rendering'))
            for record in caplog.records
            for match in [_CONFIGURED_FILTERS_PATTERN.match(record.getMessage())]
            if match is not None
        ]
        assert configured_lines == [('odometer', 'none')]
        # And the line was emitted at INFO, not DEBUG — a user
        # consulting a default-INFO log must see it.
        info_messages: set[str] = {
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.INFO
            and _CONFIGURED_FILTERS_PATTERN.match(record.getMessage())
        }
        assert "Resource 'odometer' configured filters: none" in info_messages

    def test_resource_with_last_change_date_filter_logs_iso_value(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        # Maintenance POs with a configured ``last_change_date`` floor —
        # the real-world reproducer that motivated this observability.
        configured_floor_iso: str = '2026-04-01T00:00:00+00:00'
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: maintenance_purchase_orders\n'
                '    incremental: true\n'
                '    filters:\n'
                f"      last_change_date: '{configured_floor_iso}'\n"
            ),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                '/CustomerDataAPI/maintenance/purchase-orders/basic-query': (
                    lambda _request: httpx.Response(
                        200,
                        content=_page_body(
                            items=[
                                {
                                    'poNumber': 1,
                                    'poDetailsId': 1,
                                    'poLineNumber': 1,
                                    'lastChangeDate': record_instant.isoformat(),
                                    'lastChangeRecordId': 1,
                                }
                            ],
                            total_count=1,
                            total_pages=1,
                        ),
                    )
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        configured_renderings: list[str] = [
            match.group('rendering')
            for record in caplog.records
            for match in [_CONFIGURED_FILTERS_PATTERN.match(record.getMessage())]
            if match is not None
            and match.group('resource') == 'maintenance_purchase_orders'
        ]
        assert len(configured_renderings) == 1
        rendering: str = configured_renderings[0]
        # The configured value, rendered as ISO 8601, appears verbatim
        # — a reader greps for the value they typed in YAML.
        assert f'last_change_date={configured_floor_iso}' in rendering


class TestResolvedQueryParametersLog:
    """
    Each per-resource processing iteration emits a DEBUG line showing
    the resolved query parameters that will go on the wire after
    window resolution, lookback, and any other transformations the
    orchestrator applies between the config and the request. Together
    with the configured-filters INFO line, a reader can answer "did
    my filter make it onto the wire?".
    """

    def test_bootstrap_run_logs_configured_value_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del quiet_setup_logger
        # On a bootstrap run there is no prior metadata, so no window
        # resolution shifts the configured value — the resolved query
        # echoes the configured floor.
        configured_floor_iso: str = '2026-04-01T00:00:00+00:00'
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '    filters:\n'
                f"      last_change_date: '{configured_floor_iso}'\n"
            ),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        resolved_renderings: list[str] = [
            match.group('rendering')
            for record in caplog.records
            for match in [_RESOLVED_QUERY_PATTERN.match(record.getMessage())]
            if match is not None and match.group('resource') == 'vehicles'
        ]
        assert len(resolved_renderings) == 1
        rendering: str = resolved_renderings[0]
        # The resolved query carries the configured value verbatim
        # because no window resolution has shifted it.
        assert f'last_change_date={configured_floor_iso}' in rendering
        # ``lessee_codes`` is required and renders as a Python list
        # for stability across endpoint filter schemas. The fleet
        # config in ``_YAML_BODY_TEMPLATE`` carries an
        # ``organization_id`` that is merged into the codes list at
        # load time; the resolved query reflects the merged list.
        assert "lessee_codes=['ABCD', 'ORG1']" in rendering
        # ``last_change_record_id`` is unset and must render
        # explicitly as ``None`` — a reader needs to see "this
        # parameter is unset" as a distinct outcome from "this
        # parameter wasn't logged."
        assert 'last_change_record_id=None' in rendering

    def test_resolved_line_is_debug_level(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # The resolved line is DEBUG — detail for a user actively
        # diagnosing query behavior, not steady-state INFO noise.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        # Capture at INFO only — the resolved line should not appear.
        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()
        info_only_resolved: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _RESOLVED_QUERY_PATTERN.match(record.getMessage())
        ]
        assert info_only_resolved == []

        caplog.clear()

        # Capture at DEBUG — now it appears.
        with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()
        debug_resolved: list[logging.LogRecord] = [
            record
            for record in caplog.records
            if _RESOLVED_QUERY_PATTERN.match(record.getMessage())
        ]
        assert len(debug_resolved) == 1
        assert debug_resolved[0].levelno == logging.DEBUG

    def test_steady_state_incremental_logs_resolved_window_not_raw_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # When prior metadata exists, ``ResourcePreparer.resolve_window``
        # takes the maximum of (configured floor, prior most-recent -
        # lookback). With a recent prior watermark and a far-back
        # configured floor, the resolved value is the lookback-shifted
        # prior watermark — not the configured floor. The resolved-query
        # log line must reflect what actually goes on the wire.
        del quiet_setup_logger
        configured_floor_iso: str = '2024-01-01T00:00:00+00:00'
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '    filters:\n'
                f"      last_change_date: '{configured_floor_iso}'\n"
            ),
            extra_sections='incremental:\n  lookback_days: 7\n',
        )
        # Seed prior metadata: most-recent record at 2026-01-15. With
        # lookback_days=7 the resolver computes 2026-01-08 as the
        # lookback anchor, which is later than the 2024-01-01
        # configured floor — so the resolved window_start is
        # 2026-01-08 (the lookback anchor wins).
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_record_utc: datetime = datetime(2026, 1, 15, tzinfo=UTC)
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        configured_filters_with_floor = VehiclesFilters(
            last_change_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(configured_filters_with_floor),
        )

        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.DEBUG, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        configured_renderings: list[str] = [
            match.group('rendering')
            for record in caplog.records
            for match in [_CONFIGURED_FILTERS_PATTERN.match(record.getMessage())]
            if match is not None and match.group('resource') == 'vehicles'
        ]
        resolved_renderings: list[str] = [
            match.group('rendering')
            for record in caplog.records
            for match in [_RESOLVED_QUERY_PATTERN.match(record.getMessage())]
            if match is not None and match.group('resource') == 'vehicles'
        ]
        assert len(configured_renderings) == 1
        assert len(resolved_renderings) == 1
        # Item 1 line shows the user-typed value verbatim.
        assert f'last_change_date={configured_floor_iso}' in configured_renderings[0]
        # Item 2 line shows a different value — the lookback-shifted
        # prior watermark — proving the resolution is visible.
        resolved_iso_expected: str = (prior_record_utc - timedelta(days=7)).isoformat()
        assert f'last_change_date={resolved_iso_expected}' in resolved_renderings[0]
        # And specifically NOT the configured floor.
        assert (
            f'last_change_date={configured_floor_iso}' not in resolved_renderings[0]
        )


# =============================================================================
# Per-resource window-resolution audit log line
# =============================================================================


_WINDOW_AUDIT_PATTERN: re.Pattern[str] = re.compile(
    r"^Resource '(?P<resource>[^']+)' window_start audit: (?P<rendering>.*)$"
)


class TestWindowResolutionAuditLog:
    """
    For every input that contributes to incremental ``window_start``
    resolution, the orchestrator emits a single per-resource INFO line
    showing the input values alongside the resolved value so a reader
    can recognize which input drove the result. Snapshot resources
    have no window resolution and emit no audit line.

    The canonical regression scenario is the
    ``earliest_date``-overrides-``filters.last_change_date`` case from
    the issue: a user-configured filter floor gets silently replaced
    by the project-level ``earliest_date`` floor when ``window_start``
    is set, and the only way to diagnose that without the audit was
    to read the resolution source.
    """

    @staticmethod
    def _audit_rendering(
        caplog: pytest.LogCaptureFixture,
        resource_name: str,
    ) -> str:
        matching: list[str] = [
            match.group('rendering')
            for record in caplog.records
            for match in [_WINDOW_AUDIT_PATTERN.match(record.getMessage())]
            if match is not None and match.group('resource') == resource_name
        ]
        assert len(matching) == 1, (
            f"expected exactly one window_start audit line for "
            f'{resource_name!r}, got {matching!r}'
        )
        return matching[0]

    def test_bootstrap_run_audits_inputs_with_na_for_prior_branch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Bootstrap (no prior metadata) with an ``earliest_date``
        # configured. The audit line shows the floor as a concrete
        # date, the prior-watermark and lookback-anchor inputs as
        # ``n/a`` (this run cannot read them), and the resolved
        # window_start as the floor promoted to UTC midnight.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2026-04-25\n'
                '  lookback_days: 7\n'
            ),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        rendering: str = self._audit_rendering(caplog, 'vehicles')
        assert 'is_incremental_with_prior=False' in rendering
        assert 'earliest_date=2026-04-25' in rendering
        assert 'lookback_days=7' in rendering
        assert 'prior_most_recent_record_utc=n/a' in rendering
        assert 'lookback_anchor=n/a' in rendering
        # earliest_date promoted to UTC midnight is the resolved value.
        assert 'resolved_window_start=2026-04-25T00:00:00+00:00' in rendering

    def test_steady_state_run_audits_lookback_anchor_when_it_wins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Steady-state run where the lookback-shifted prior watermark
        # is later than the configured floor — the lookback anchor
        # wins. A reader of the audit line can correlate the inputs
        # to the resolved value and see the anchor matches.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2024-01-01\n'
                '  lookback_days: 7\n'
            ),
        )
        prior_record_utc: datetime = datetime(2026, 1, 15, tzinfo=UTC)
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        record_instant: datetime = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        rendering: str = self._audit_rendering(caplog, 'vehicles')
        expected_lookback_anchor: str = (
            (prior_record_utc - timedelta(days=7)).isoformat()
        )
        assert 'is_incremental_with_prior=True' in rendering
        assert 'earliest_date=2024-01-01' in rendering
        assert 'lookback_days=7' in rendering
        assert (
            f'prior_most_recent_record_utc={prior_record_utc.isoformat()}'
            in rendering
        )
        assert f'lookback_anchor={expected_lookback_anchor}' in rendering
        # The lookback anchor (2026-01-08) is later than the
        # earliest_date floor (2024-01-01), so the anchor wins.
        assert f'resolved_window_start={expected_lookback_anchor}' in rendering

    def test_steady_state_run_audits_earliest_date_when_it_wins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # The reverse: a recent ``earliest_date`` floor sits later than
        # the lookback-shifted prior watermark — the floor wins. This
        # is the case the issue described: a user-configured filter
        # floor that gets silently overwritten by the project floor
        # without the audit, the only way to identify the winning
        # input was to know the resolution rules.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2026-04-25\n'
                '  lookback_days: 7\n'
            ),
        )
        # Prior watermark sits well before the floor, so the floor
        # wins after the max() in resolve_window.
        prior_record_utc: datetime = datetime(2026, 1, 15, tzinfo=UTC)
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        record_instant: datetime = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        rendering: str = self._audit_rendering(caplog, 'vehicles')
        expected_lookback_anchor: str = (
            (prior_record_utc - timedelta(days=7)).isoformat()
        )
        # All inputs are visible, including the lookback_anchor that
        # *didn't* win.
        assert 'earliest_date=2026-04-25' in rendering
        assert f'lookback_anchor={expected_lookback_anchor}' in rendering
        # The earliest_date promoted to UTC midnight is the resolved
        # value — the input that won.
        assert 'resolved_window_start=2026-04-25T00:00:00+00:00' in rendering
        # And specifically NOT the lookback anchor.
        assert (
            f'resolved_window_start={expected_lookback_anchor}' not in rendering
        )

    def test_configured_filter_appears_as_input_and_drives_resolution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Bootstrap run with ``filters.last_change_date`` configured
        # and no other inputs. The audit line shows the configured
        # filter as one of the inputs and as the resolved value —
        # closing the gap that motivated the configured-filter
        # participation fix.
        del quiet_setup_logger
        configured_filter_iso: str = '2026-04-01T00:00:00+00:00'
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml=(
                '  - name: vehicles\n'
                '    incremental: true\n'
                '    filters:\n'
                f"      last_change_date: '{configured_filter_iso}'\n"
            ),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        rendering: str = self._audit_rendering(caplog, 'vehicles')
        # The configured filter is now a named input in the audit
        # rendering (was absent before this fix).
        assert (
            f'configured_filter_last_change_date={configured_filter_iso}'
            in rendering
        )
        # And it drives the resolution: with no floor and no prior
        # watermark, the configured filter is the resolved value.
        assert f'resolved_window_start={configured_filter_iso}' in rendering

    def test_snapshot_resource_emits_no_audit_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Snapshot resources have no window resolution to audit; the
        # line must not be emitted.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.INFO, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        audit_lines: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _WINDOW_AUDIT_PATTERN.match(record.getMessage())
        ]
        assert audit_lines == []


# =============================================================================
# earliest_date data-gap warning
# =============================================================================


_GAP_WARNING_PATTERN: re.Pattern[str] = re.compile(
    r'^Resource \'(?P<resource>[^\']+)\': earliest_date floor '
)


class TestEarliestDateGapWarning:
    """
    End-to-end smoke tests for the WARNING emitted when
    ``earliest_date`` forces a data gap. The warning's per-scenario
    trigger logic is exhaustively covered by parametrized unit tests
    in :mod:`tests._pipeline.test_log_format`; the orchestrator-level
    tests here just confirm the warning is wired in at the right
    severity and reaches the user log.
    """

    def test_steady_state_with_gap_emits_warning_at_warning_level(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # The "earliest_date_creates_large_gap" scenario from the
        # table: floor at 2026-04-25, prior watermark at 2026-03-27,
        # lookback 7d → anchor at 2026-03-20. Floor strictly above
        # anchor, warning fires.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2026-04-25\n'
                '  lookback_days: 7\n'
            ),
        )
        prior_record_utc: datetime = datetime(2026, 3, 27, tzinfo=UTC)
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.WARNING, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        gap_warnings: list[logging.LogRecord] = [
            record
            for record in caplog.records
            if _GAP_WARNING_PATTERN.match(record.getMessage())
            and record.levelno == logging.WARNING
        ]
        assert len(gap_warnings) == 1
        message: str = gap_warnings[0].getMessage()
        assert "'vehicles'" in message
        assert '2026-04-25T00:00:00+00:00' in message  # floor / resolved
        assert '2026-03-20T00:00:00+00:00' in message  # lookback anchor
        assert prior_record_utc.isoformat() in message  # gap lower bound
        assert 'remove or lower earliest_date' in message

    def test_bootstrap_with_floor_does_not_warn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Bootstrap with ``earliest_date`` only — there's no prior
        # watermark, so there's no "gap" concept. The user is choosing
        # a starting point; warning would be noise.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2026-04-25\n'
                '  lookback_days: 7\n'
            ),
        )
        record_instant: datetime = datetime(2026, 5, 1, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.WARNING, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        gap_warnings: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _GAP_WARNING_PATTERN.match(record.getMessage())
        ]
        assert gap_warnings == []

    def test_steady_state_with_inert_floor_does_not_warn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # ``earliest_date`` set but lower than the lookback anchor —
        # no gap, no warning.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: vehicles\n    incremental: true\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2024-01-01\n'
                '  lookback_days: 7\n'
            ),
        )
        prior_record_utc: datetime = datetime(2026, 1, 15, tzinfo=UTC)
        prior_handler: ParquetHandler = ParquetHandler(
            working_directory=tmp_path / 'data',
            resource_name='vehicles',
        )
        prior_handler.from_dataframe(
            Vehicle.records_to_dataframe(
                [
                    Vehicle.model_validate(
                        {
                            'holmanVehicleNumber': 'V_OLD',
                            'lastChangeDate': prior_record_utc.isoformat(),
                        }
                    )
                ]
            )
        )
        _seed_metadata(
            config_path=config_path,
            resource_name='vehicles',
            most_recent_record_utc=prior_record_utc,
            filters_hash=hash_filter_model(VehiclesFilters()),
        )
        record_instant: datetime = datetime(2026, 4, 21, tzinfo=UTC)
        handler: _RecordingHandler = _build_handler(
            {
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V_NEW', last_change_date=record_instant)],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.WARNING, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        gap_warnings: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _GAP_WARNING_PATTERN.match(record.getMessage())
        ]
        assert gap_warnings == []

    def test_snapshot_resource_with_floor_does_not_warn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        quiet_setup_logger: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # ``earliest_date`` is in ``incremental:`` config and applies
        # only to incremental resources. Snapshot endpoints have no
        # window resolution to audit and emit no gap warning.
        del quiet_setup_logger
        config_path: Path = _write_config(
            tmp_path,
            resources_yaml='  - name: odometer\n',
            extra_sections=(
                'incremental:\n'
                '  earliest_date: 2026-04-25\n'
                '  lookback_days: 7\n'
            ),
        )
        handler: _RecordingHandler = _build_handler(
            {
                _ODOMETER_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_odometer_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with caplog.at_level(logging.WARNING, logger=PACKAGE_NAME):
            Orchestrator(config_path=config_path).run()

        gap_warnings: list[str] = [
            record.getMessage()
            for record in caplog.records
            if _GAP_WARNING_PATTERN.match(record.getMessage())
        ]
        assert gap_warnings == []


# =============================================================================
# Public-surface check
# =============================================================================


def test_orchestrator_is_exported_from_pyholman_top_level() -> None:
    # Import the package via the binding pulled at the top of this
    # module rather than re-importing it here (ruff PLC0415); the
    # ``orchestrator_module`` import already pulls ``pyholman`` as a
    # side effect, so the top-level package binding is reachable
    # through ``orchestrator_module``'s parent.
    import pyholman as pyholman_top_level  # noqa: PLC0415 — local import keeps the public-surface check focused on the binding under test.

    assert pyholman_top_level.Orchestrator is Orchestrator
