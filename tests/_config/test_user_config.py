# tests/_config/test_user_config.py
"""Tests for UserConfig — the top-level loader and aggregator."""

import logging
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import HttpUrl, ValidationError

from pyholman._config import (
    MaintenancePurchaseOrdersResourceConfig,
    OdometerResourceConfig,
    OutputFormat,
    ParquetCompression,
    RetryConfig,
    UserConfig,
    VehiclesResourceConfig,
)

__all__: list[str] = []


# Minimal valid YAML body used across many tests. Excludes the credentials
# client_secret (by design — it is injected from the environment).
# Required sections: credentials, fleet, resources. ``api`` defaults to
# ``ApiConfig()`` when omitted; ``working_directory`` is included here
# because the round-trip test asserts on its resolved value.
_VALID_YAML_BODY: str = dedent(
    """\
    credentials:
      client_id: 'my-client-id'
    api:
      base_url: 'https://api.holman.solutions'
    fleet:
      organization_id: 'ORG1'
      lessee_codes:
        - 'ABCD'
        - 'wxyz'
    working_directory: '/tmp/pyholman_data'
    resources:
      - name: vehicles
    """
)


# Variant body with every defaulted section explicitly populated. Used by
# tests that exercise overrides rather than defaults.
_FULL_YAML_BODY: str = dedent(
    """\
    credentials:
      client_id: 'my-client-id'
    api:
      base_url: 'https://api.holman.solutions'
    fleet:
      organization_id: 'ORG1'
      lessee_codes:
        - 'ABCD'
        - 'wxyz'
    working_directory: '/tmp/pyholman_data'
    output:
      format: parquet
    incremental:
      lookback_days: 14
    logger:
      console_level: INFO
    resources:
      - name: vehicles
    """
)


def _write_yaml(tmp_path: Path, body: str) -> Path:
    """Write ``body`` to a fresh YAML file under ``tmp_path`` and return it."""
    config_file: Path = tmp_path / 'user_config.yaml'
    config_file.write_text(body)
    return config_file


class TestUserConfigHappyPath:
    def test_round_trip_all_fields_populated(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, _FULL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert config.credentials.client_id == 'my-client-id'
        assert config.credentials.client_secret.get_secret_value() == (
            'test-secret-value'
        )

        assert isinstance(config.api.base_url, HttpUrl)
        assert str(config.api.base_url).startswith('https://api.holman.solutions')

        # ``organization_id`` is merged into lessee_codes at load time;
        # downstream code sees a single tuple.
        assert not hasattr(config.fleet, 'organization_id')
        assert config.fleet.lessee_codes == ('ABCD', 'ORG1', 'WXYZ')

        assert config.working_directory == Path('/tmp/pyholman_data').resolve()
        assert config.output.format is OutputFormat.PARQUET
        assert config.output.compression is ParquetCompression.SNAPPY

        assert config.incremental.lookback_days == 14

        assert config.logger.console_level == logging.INFO
        assert config.logger.file_path is None
        assert config.logger.file_level is None

    def test_example_yaml_loads(self, tmp_path: Path) -> None:
        # The shipped example should round-trip through the loader — this
        # guards against the example and the schema drifting apart.
        example_source: Path = (
            Path(__file__).resolve().parents[2] / 'user_config.example.yaml'
        )
        # Copy to tmp_path so tilde-expansion tests don't interfere with
        # the in-repo file. The loader reads it directly, so a copy is
        # sufficient.
        destination: Path = tmp_path / 'example.yaml'
        destination.write_text(example_source.read_text())

        config: UserConfig = UserConfig.from_yaml(destination)
        assert config.credentials.client_id.startswith('cust-api.org-')


class TestUserConfigEnvironmentSecret:
    def test_missing_env_var_raises_naming_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv('HOLMAN_CLIENT_SECRET', raising=False)
        config_file: Path = _write_yaml(tmp_path, _VALID_YAML_BODY)

        with pytest.raises(RuntimeError, match='HOLMAN_CLIENT_SECRET'):
            UserConfig.from_yaml(config_file)

    def test_empty_env_var_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('HOLMAN_CLIENT_SECRET', '')
        config_file: Path = _write_yaml(tmp_path, _VALID_YAML_BODY)

        with pytest.raises(RuntimeError, match='HOLMAN_CLIENT_SECRET'):
            UserConfig.from_yaml(config_file)

    def test_yaml_supplied_secret_rejected(self, tmp_path: Path) -> None:
        yaml_with_secret: str = dedent(
            """\
            credentials:
              client_id: 'my-client-id'
              client_secret: 'leaked-into-yaml'
            api:
              base_url: 'https://api.holman.solutions'
            fleet:
              lessee_codes: ['ABCD']
            """
        )
        config_file: Path = _write_yaml(tmp_path, yaml_with_secret)

        with pytest.raises(RuntimeError, match='HOLMAN_CLIENT_SECRET'):
            UserConfig.from_yaml(config_file)


class TestUserConfigFileErrors:
    def test_missing_file_raises_with_resolved_path(
        self,
        tmp_path: Path,
    ) -> None:
        missing: Path = tmp_path / 'does-not-exist.yaml'
        with pytest.raises(FileNotFoundError) as excinfo:
            UserConfig.from_yaml(missing)
        assert str(missing) in str(excinfo.value)

    def test_empty_yaml_rejected(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, '')
        with pytest.raises(ValueError, match='empty'):
            UserConfig.from_yaml(config_file)

    def test_non_dict_root_rejected(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, '- 1\n- 2\n')
        with pytest.raises(TypeError):
            UserConfig.from_yaml(config_file)

    def test_empty_dict_rejected(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, '{}\n')
        with pytest.raises(ValueError, match='empty dictionary'):
            UserConfig.from_yaml(config_file)


class TestUserConfigWorkingDirectory:
    """
    Tests for the ``working_directory`` field validator.

    Behavior mirrors the validator that used to live on
    ``OutputConfig.directory`` — tilde expansion, relative-path
    resolution, ``Path`` instances accepted, no disk access. These
    tests exercise the validator through ``model_validate`` rather
    than ``UserConfig.from_yaml`` to keep them independent of the
    YAML loader and the ``HOLMAN_CLIENT_SECRET`` environment fixture.
    """

    @staticmethod
    def _build_minimal_payload(working_directory: object) -> dict[str, object]:
        """Return the smallest payload that satisfies every required section."""
        return {
            'credentials': {
                'client_id': 'my-client-id',
                'client_secret': 'test-secret-value',
            },
            'api': {'base_url': 'https://api.holman.solutions'},
            'fleet': {'lessee_codes': ['ABCD']},
            'working_directory': working_directory,
            'resources': [{'name': 'vehicles'}],
        }

    def test_tilde_expanded_to_absolute(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('HOME', str(tmp_path))
        payload: dict[str, object] = self._build_minimal_payload('~/pyholman_data')
        config: UserConfig = UserConfig.model_validate(payload)
        assert config.working_directory.is_absolute()
        assert str(tmp_path) in str(config.working_directory)

    def test_relative_path_resolved(self) -> None:
        payload: dict[str, object] = self._build_minimal_payload('./relative/sub')
        config: UserConfig = UserConfig.model_validate(payload)
        assert config.working_directory.is_absolute()

    def test_path_object_accepted(self, tmp_path: Path) -> None:
        payload: dict[str, object] = self._build_minimal_payload(tmp_path)
        config: UserConfig = UserConfig.model_validate(payload)
        assert config.working_directory == tmp_path.resolve()

    def test_directory_not_created(self, tmp_path: Path) -> None:
        target: Path = tmp_path / 'not-yet'
        payload: dict[str, object] = self._build_minimal_payload(target)
        config: UserConfig = UserConfig.model_validate(payload)
        assert config.working_directory == target.resolve()
        assert not target.exists()


class TestUserConfigSchemaMigration:
    """
    Guardrail for the 9.5 schema change: ``directory`` used to live on
    ``OutputConfig`` and is now ``UserConfig.working_directory``. Stale
    YAML using the old shape must surface as an ``extra='forbid'``
    error naming ``directory`` so the migration signal is unmistakable.
    """

    def test_old_output_directory_shape_rejected(self, tmp_path: Path) -> None:
        old_shape: str = dedent(
            """\
            credentials:
              client_id: 'my-client-id'
            api:
              base_url: 'https://api.holman.solutions'
            fleet:
              lessee_codes: ['ABCD']
            output:
              directory: '/tmp/pyholman_data'
              format: parquet
            """
        )
        config_file: Path = _write_yaml(tmp_path, old_shape)

        with pytest.raises(ValidationError, match='directory'):
            UserConfig.from_yaml(config_file)


class TestUserConfigDefaults:
    """
    YAML containing only the three required sections — credentials,
    api, fleet — must load successfully and surface documented
    defaults for everything else.
    """

    _MINIMAL_YAML_BODY: str = dedent(
        """\
        credentials:
          client_id: 'my-client-id'
        api:
          base_url: 'https://api.holman.solutions'
        fleet:
          lessee_codes: ['ABCD']
        resources:
          - name: vehicles
        """
    )

    def test_minimal_yaml_loads(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        # Must not raise.
        UserConfig.from_yaml(config_file)

    def test_working_directory_defaults_to_cwd_pyholman_data(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pin cwd to a fresh directory so the assertion does not race
        # against any developer's real ``pyholman_data`` directory.
        monkeypatch.chdir(tmp_path)

        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        expected: Path = (tmp_path / 'pyholman_data').resolve()
        assert config.working_directory == expected

    def test_default_working_directory_is_not_created_at_load_time(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Loading config must not touch disk. The directory is created
        # lazily by ``build_resource_paths`` on first write.
        monkeypatch.chdir(tmp_path)

        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert config.working_directory.is_absolute()
        assert config.working_directory.exists() is False

    def test_output_defaults_to_parquet_with_snappy(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)
        assert config.output.format is OutputFormat.PARQUET
        assert config.output.compression is ParquetCompression.SNAPPY

    def test_incremental_defaults_to_seven_day_lookback(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)
        assert config.incremental.lookback_days == 7
        assert config.incremental.earliest_date is None

    def test_logger_defaults_to_warning_console_no_file(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, self._MINIMAL_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)
        assert config.logger.console_level == logging.WARNING
        assert config.logger.file_path is None
        assert config.logger.file_level is None


class TestUserConfigSchemaErrors:
    def test_unknown_top_level_section_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        body_with_typo: str = _VALID_YAML_BODY + 'unknown_section:\n  foo: 1\n'
        config_file: Path = _write_yaml(tmp_path, body_with_typo)

        with pytest.raises(ValidationError, match='unknown_section'):
            UserConfig.from_yaml(config_file)

    def test_missing_required_section_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        # Drop the 'credentials' section entirely. Required sections are
        # credentials, fleet, and resources; the rest now have defaults.
        body: str = dedent(
            """\
            fleet:
              lessee_codes: ['ABCD']
            resources:
              - name: vehicles
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)

        with pytest.raises(ValidationError, match='credentials'):
            UserConfig.from_yaml(config_file)

    def test_omitted_api_section_uses_defaults(self, tmp_path: Path) -> None:
        # ``api`` is no longer required; omitting it should produce a
        # default-constructed ``ApiConfig`` (production base URL, page
        # size 200, certifi roots).
        body: str = dedent(
            """\
            credentials:
              client_id: 'cid'
            fleet:
              lessee_codes: ['ABCD']
            resources:
              - name: vehicles
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)

        config: UserConfig = UserConfig.from_yaml(config_file)

        assert str(config.api.base_url) == 'https://api.holman.solutions/'
        assert config.api.page_size == 200
        assert config.api.use_truststore is False

    def test_credentials_section_as_list_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        bad_body: str = dedent(
            """\
            credentials:
              - 'not a mapping'
            api:
              base_url: 'https://api.holman.solutions'
            fleet:
              lessee_codes: ['ABCD']
            """
        )
        config_file: Path = _write_yaml(tmp_path, bad_body)

        with pytest.raises(TypeError, match='credentials'):
            UserConfig.from_yaml(config_file)


class TestUserConfigRetryDefaults:
    _DEFAULT_MAX_ATTEMPTS: int = 5
    _DEFAULT_BACKOFF_MAX_SECONDS: float = 60.0

    def test_omitting_retry_section_yields_defaults(self, tmp_path: Path) -> None:
        # ``_VALID_YAML_BODY`` does not set a ``retry:`` section; the
        # default factory must populate one with the documented defaults.
        config_file: Path = _write_yaml(tmp_path, _VALID_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert isinstance(config.retry, RetryConfig)
        assert config.retry.max_attempts == self._DEFAULT_MAX_ATTEMPTS
        assert config.retry.backoff_max_seconds == self._DEFAULT_BACKOFF_MAX_SECONDS

    def test_yaml_override_takes_precedence(self, tmp_path: Path) -> None:
        body_with_retry: str = _VALID_YAML_BODY + dedent(
            """\
            retry:
              max_attempts: 2
              backoff_max_seconds: 15.0
            """
        )
        config_file: Path = _write_yaml(tmp_path, body_with_retry)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert config.retry.max_attempts == 2
        assert config.retry.backoff_max_seconds == 15.0

    def test_partial_yaml_override_keeps_untouched_defaults(
        self,
        tmp_path: Path,
    ) -> None:
        body_with_partial_retry: str = _VALID_YAML_BODY + dedent(
            """\
            retry:
              max_attempts: 10
            """
        )
        config_file: Path = _write_yaml(tmp_path, body_with_partial_retry)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert config.retry.max_attempts == 10
        assert config.retry.backoff_max_seconds == self._DEFAULT_BACKOFF_MAX_SECONDS

    def test_invalid_retry_value_raises(self, tmp_path: Path) -> None:
        body_with_bad_retry: str = _VALID_YAML_BODY + dedent(
            """\
            retry:
              max_attempts: 0
            """
        )
        config_file: Path = _write_yaml(tmp_path, body_with_bad_retry)
        with pytest.raises(ValidationError, match='max_attempts'):
            UserConfig.from_yaml(config_file)


class TestUserConfigImmutability:
    def test_is_frozen_at_every_level(self, tmp_path: Path) -> None:
        config_file: Path = _write_yaml(tmp_path, _VALID_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        with pytest.raises(ValidationError):
            config.api = config.api  # type: ignore[misc]

        with pytest.raises(ValidationError):
            config.fleet.organization_id = 'NEW'  # type: ignore[misc]


class TestUserConfigResources:
    def test_missing_resources_section_raises(self, tmp_path: Path) -> None:
        # ``resources`` is required and ``min_length=1``: a config that
        # omits the section entirely fails validation at load time.
        body_without_resources: str = dedent(
            """\
            credentials:
              client_id: 'my-client-id'
            api:
              base_url: 'https://api.holman.solutions'
            fleet:
              organization_id: 'ORG1'
              lessee_codes:
                - 'ABCD'
            working_directory: '/tmp/pyholman_data'
            """
        )
        config_file: Path = _write_yaml(tmp_path, body_without_resources)

        with pytest.raises(ValidationError, match='resources'):
            UserConfig.from_yaml(config_file)

    def test_empty_resources_list_raises(self, tmp_path: Path) -> None:
        body_with_empty_resources: str = dedent(
            """\
            credentials:
              client_id: 'my-client-id'
            api:
              base_url: 'https://api.holman.solutions'
            fleet:
              organization_id: 'ORG1'
              lessee_codes:
                - 'ABCD'
            working_directory: '/tmp/pyholman_data'
            resources: []
            """
        )
        config_file: Path = _write_yaml(tmp_path, body_with_empty_resources)

        with pytest.raises(ValidationError, match='resources'):
            UserConfig.from_yaml(config_file)

    def test_three_resources_preserved_in_order(self, tmp_path: Path) -> None:
        body: str = _VALID_YAML_BODY + dedent(
            """\
            resources:
              - name: vehicles
                incremental: true
                filters:
                  status_codes: [1]
              - name: maintenance_purchase_orders
                incremental: true
              - name: odometer
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert len(config.resources) == 3
        assert isinstance(config.resources[0], VehiclesResourceConfig)
        assert config.resources[0].incremental is True
        assert config.resources[0].filters.status_codes == (1,)
        assert isinstance(config.resources[1], MaintenancePurchaseOrdersResourceConfig)
        assert config.resources[1].incremental is True
        assert isinstance(config.resources[2], OdometerResourceConfig)
        assert config.resources[2].incremental is False

    def test_duplicate_resource_names_rejected(self, tmp_path: Path) -> None:
        body: str = _VALID_YAML_BODY + dedent(
            """\
            resources:
              - name: vehicles
              - name: vehicles
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)

        with pytest.raises(ValidationError, match='vehicles'):
            UserConfig.from_yaml(config_file)

    def test_unknown_resource_name_rejected(self, tmp_path: Path) -> None:
        body: str = _VALID_YAML_BODY + dedent(
            """\
            resources:
              - name: bogus_resource
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)

        with pytest.raises(ValidationError):
            UserConfig.from_yaml(config_file)


class TestUserConfigFindResource:
    """
    ``UserConfig.find_resource`` returns the typed config variant for a
    configured resource name, or raises a friendly ``ValueError``
    listing the configured names.
    """

    def test_returns_matching_resource(self, tmp_path: Path) -> None:
        body: str = _VALID_YAML_BODY + dedent(
            """\
            resources:
              - name: vehicles
                incremental: true
              - name: odometer
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)
        config: UserConfig = UserConfig.from_yaml(config_file)

        # Returns the actual ResourceConfig instance present in the tuple.
        odometer = config.find_resource('odometer')
        assert odometer is config.resources[1]
        assert odometer.name == 'odometer'

        vehicles = config.find_resource('vehicles')
        assert vehicles is config.resources[0]
        assert vehicles.name == 'vehicles'

    def test_unknown_name_raises_listing_configured_names(self, tmp_path: Path) -> None:
        body: str = _VALID_YAML_BODY + dedent(
            """\
            resources:
              - name: vehicles
              - name: odometer
            """
        )
        config_file: Path = _write_yaml(tmp_path, body)
        config: UserConfig = UserConfig.from_yaml(config_file)

        with pytest.raises(ValueError, match='contacts') as caught:
            config.find_resource('contacts')

        message: str = str(caught.value)
        assert 'vehicles' in message
        assert 'odometer' in message

    def test_unknown_name_with_one_configured_lists_that_name(
        self,
        tmp_path: Path,
    ) -> None:
        # ``resources`` is now ``min_length=1`` so the empty-resources
        # error path is unreachable from a loaded config. The friendly
        # ``find_resource`` error still has to surface the configured
        # names; this test pins that behavior with a minimal one-entry
        # list.
        config_file: Path = _write_yaml(tmp_path, _VALID_YAML_BODY)
        config: UserConfig = UserConfig.from_yaml(config_file)

        assert len(config.resources) == 1
        with pytest.raises(ValueError, match='contacts') as caught:
            config.find_resource('contacts')
        # The configured 'vehicles' resource shows up in the message.
        assert 'vehicles' in str(caught.value)
