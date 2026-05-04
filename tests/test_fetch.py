# tests/test_fetch.py
"""Tests for the public ``fetch`` entry point."""

import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd
import pytest

from pyholman import HolmanError, RateLimitError, TransientHolmanError, fetch
from pyholman._endpoints.registry import ENDPOINT_NAMES
from tests._helpers.http import (
    _install_mock_transport,
    _page_body,
    _RecordingHandler,
)

__all__: list[str] = []


# =============================================================================
# Holman-shaped response helpers (mirrors tests/test_client.py patterns)
# =============================================================================


_TOKEN_ENDPOINT_PATH: str = '/sso/sts/connect/token'
_VEHICLES_ENDPOINT_PATH: str = '/CustomerDataAPI/vehicles/basic-query'
_TOKEN_RESPONSE_BODY: bytes = (
    b'{"access_token":"test-token",'
    b'"token_type":"Bearer",'
    b'"expires_in":3600,'
    b'"scope":"read"}'
)


def _vehicle_item(holman_vehicle_number: str) -> dict[str, object]:
    """A minimal vehicles response item using camelCase Holman aliases."""
    return {'holmanVehicleNumber': holman_vehicle_number}


def _always_token_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=_TOKEN_RESPONSE_BODY)


@pytest.fixture
def silenced_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry waits instantaneous."""

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(time, 'sleep', _no_sleep)


# =============================================================================
# Common kwargs
# =============================================================================


_FETCH_KWARGS: dict[str, object] = {
    'client_id': 'my-client-id',
    'client_secret': 'my-secret',
    'lessee_codes': ['ABCD'],
}


# =============================================================================
# Endpoint validation
# =============================================================================


class TestUnknownEndpoint:
    def test_unknown_endpoint_raises_value_error_listing_valid_names(self) -> None:
        with pytest.raises(ValueError, match='bogus') as caught:
            fetch(endpoint='bogus', **_FETCH_KWARGS)  # type: ignore[arg-type]
        message: str = str(caught.value)
        for known in ENDPOINT_NAMES:
            assert known in message


# =============================================================================
# Happy-path returns
# =============================================================================


class TestSinglePage:
    def test_returns_dataframe_for_single_page_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1'), _vehicle_item('V2')],
                        total_count=2,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        dataframe: pd.DataFrame = fetch(endpoint='vehicles', **_FETCH_KWARGS)

        assert isinstance(dataframe, pd.DataFrame)
        assert len(dataframe) == 2
        # Column names are the model's snake_case Python attributes,
        # not Holman's camelCase aliases.
        assert 'holman_vehicle_number' in dataframe.columns
        assert dataframe['holman_vehicle_number'].tolist() == ['V1', 'V2']


class TestMultiPage:
    def test_returns_dataframe_for_multi_page_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        total_pages: int = 3
        items_per_page: int = 2

        def _page_handler(request: httpx.Request) -> httpx.Response:
            parsed: dict[str, list[str]] = parse_qs(urlsplit(str(request.url)).query)
            page_number: int = int(parsed['pageNumber'][0])
            start: int = (page_number - 1) * items_per_page + 1
            items: list[dict[str, object]] = [
                _vehicle_item(f'V{start + offset}') for offset in range(items_per_page)
            ]
            return httpx.Response(
                200,
                content=_page_body(
                    items=items,
                    total_count=total_pages * items_per_page,
                    page_number=page_number,
                    total_pages=total_pages,
                ),
            )

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: _page_handler,
            }
        )
        _install_mock_transport(monkeypatch, handler)

        dataframe: pd.DataFrame = fetch(endpoint='vehicles', **_FETCH_KWARGS)

        # All rows in page-then-record order — V1..V6 across three pages.
        assert dataframe['holman_vehicle_number'].tolist() == [
            f'V{i}' for i in range(1, total_pages * items_per_page + 1)
        ]


# =============================================================================
# Empty result envelope
# =============================================================================


class TestEmptyResult:
    def test_empty_response_returns_empty_typed_dataframe(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Holman's empty-result envelope omits ``pageInfo`` and carries
        # ``message: 'No data found.'`` with an empty ``items`` list.
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
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

        dataframe: pd.DataFrame = fetch(endpoint='vehicles', **_FETCH_KWARGS)

        assert isinstance(dataframe, pd.DataFrame)
        assert len(dataframe) == 0
        # The typed-columns guarantee from records_to_dataframe means at
        # least one declared column survives the empty-input path.
        assert 'holman_vehicle_number' in dataframe.columns


# =============================================================================
# lessee_codes normalization on the wire
# =============================================================================


class TestLesseeCodeNormalization:
    def test_lessee_codes_normalized_on_wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        fetch(
            endpoint='vehicles',
            client_id='my-client-id',
            client_secret='my-secret',
            lessee_codes=['cdef', 'ABCD', 'cdef'],
        )

        data_requests: list[httpx.Request] = handler.requests_for_path(
            _VEHICLES_ENDPOINT_PATH
        )
        assert len(data_requests) == 1
        parsed: dict[str, list[str]] = parse_qs(
            urlsplit(str(data_requests[0].url)).query
        )
        # FleetConfig uppercases, deduplicates, sorts. Wire form is the
        # comma-joined canonical tuple: 'ABCD,CDEF'.
        assert parsed['lesseeCodes'] == ['ABCD,CDEF']


# =============================================================================
# use_truststore flow-through
# =============================================================================


class TestUseTruststoreFlowsThrough:
    @pytest.mark.parametrize('flag', [True, False])
    def test_flag_flows_through_to_transport_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flag: bool,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        captured_api_configs: list[object] = []
        _install_mock_transport(
            monkeypatch, handler, captured_api_configs=captured_api_configs
        )

        fetch(
            endpoint='vehicles',
            client_id='my-client-id',
            client_secret='my-secret',
            lessee_codes=['ABCD'],
            use_truststore=flag,
        )

        assert len(captured_api_configs) == 1
        api_config = captured_api_configs[0]
        # The factory receives an ApiConfig with the use_truststore
        # value the caller asked for.
        assert api_config.use_truststore is flag


# =============================================================================
# Error propagation
# =============================================================================


class TestErrorPropagation:
    def test_holman_error_propagates_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    401, content=b'unauthorized'
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with pytest.raises(HolmanError) as caught:
            fetch(endpoint='vehicles', **_FETCH_KWARGS)
        # 401 must surface as the base HolmanError, not the transient
        # subclass — orchestrators must not retry credential problems.
        assert type(caught.value) is HolmanError

    def test_transient_holman_error_propagates_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    500, content=b'boom'
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with pytest.raises(TransientHolmanError):
            fetch(endpoint='vehicles', **_FETCH_KWARGS)

    def test_rate_limit_error_propagates_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        silenced_sleep: None,
    ) -> None:
        del silenced_sleep
        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    429,
                    headers={'Retry-After': '1'},
                    content=b'slow down',
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        with pytest.raises(RateLimitError):
            fetch(endpoint='vehicles', **_FETCH_KWARGS)


# =============================================================================
# No filesystem side effects
# =============================================================================


class TestNoFilesystemSideEffects:
    def test_default_working_directory_is_not_created_at_load_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Pin cwd so the default ``working_directory`` of the
        # internally-built UserConfig points under tmp_path, not the
        # developer's real cwd.
        monkeypatch.chdir(tmp_path)
        expected_default: Path = tmp_path / 'pyholman_data'
        assert expected_default.exists() is False

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        fetch(endpoint='vehicles', **_FETCH_KWARGS)

        # Fetch must not touch disk. The directory remains absent.
        assert expected_default.exists() is False


# =============================================================================
# Logging policy untouched
# =============================================================================


class TestLoggingNotConfigured:
    def test_does_not_modify_logging_configuration(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Snapshot the package logger's state before fetch. After a
        # successful call, every observable attribute must be identical
        # — fetch must NOT call ``setup_logger`` or otherwise touch
        # logging policy. Library convention: applications decide.
        package_logger: logging.Logger = logging.getLogger('pyholman')
        handlers_before: list[logging.Handler] = list(package_logger.handlers)
        level_before: int = package_logger.level
        propagate_before: bool = package_logger.propagate

        handler = _RecordingHandler(
            {
                _TOKEN_ENDPOINT_PATH: _always_token_response,
                _VEHICLES_ENDPOINT_PATH: lambda _request: httpx.Response(
                    200,
                    content=_page_body(
                        items=[_vehicle_item('V1')],
                        total_count=1,
                        total_pages=1,
                    ),
                ),
            }
        )
        _install_mock_transport(monkeypatch, handler)

        fetch(endpoint='vehicles', **_FETCH_KWARGS)

        assert package_logger.handlers == handlers_before
        assert package_logger.level == level_before
        assert package_logger.propagate is propagate_before
