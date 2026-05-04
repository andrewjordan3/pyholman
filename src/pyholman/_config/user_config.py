# src/pyholman/_config/user_config.py
"""Top-level pyholman user configuration model."""

import logging
import os
from pathlib import Path
from typing import Any, Self

from pydantic import Field, field_validator, model_validator

from pyholman._config.api import ApiConfig
from pyholman._config.credentials import CredentialsConfig
from pyholman._config.fleet import FleetConfig
from pyholman._config.incremental import IncrementalConfig
from pyholman._config.logger import LoggerConfig
from pyholman._config.output import OutputConfig
from pyholman._config.resources import ResourceConfig
from pyholman._config.retry import RetryConfig
from pyholman._core import FrozenModel
from pyholman._core.constants import CLIENT_SECRET_ENV_VAR
from pyholman._yaml import load_yaml_from_path

__all__: list[str] = ['UserConfig']

logger: logging.Logger = logging.getLogger(__name__)


def _default_working_directory() -> Path:
    """
    Return ``Path.cwd() / 'pyholman_data'``, fully resolved.

    Resolved at call time — not at import time — so a process that
    changes its working directory between import and config load picks
    up the new cwd. The returned path is absolute; the directory itself
    is NOT created here. The per-resource :class:`StorageHandler`
    creates its resource subdirectory on first write.
    """
    return (Path.cwd() / 'pyholman_data').resolve()


class UserConfig(FrozenModel):
    """
    Top-level pyholman user configuration.

    Aggregates the section models into a single frozen, strictly
    validated tree. Callers load an instance with the
    ``UserConfig.from_yaml`` classmethod; direct construction is supported
    but the classmethod is the expected entry point because it wires the
    client secret in from the environment.

    Attribute layout matches the YAML top-level keys so a user reading
    either the YAML or the Python instance sees the same names:
    ``credentials``, ``api``, ``fleet``, ``working_directory``, ``output``,
    ``incremental``, ``retry``, ``logger``.

    ``working_directory`` defaults to ``Path.cwd() / 'pyholman_data'``,
    resolved to an absolute path. User-supplied values are tilde-
    expanded and resolved by the field validator. Existence is not
    checked at load time — the per-resource
    :class:`pyholman._storage.StorageHandler` creates the resource
    subdirectory on first write.

    Required sections: ``credentials``, ``api``, ``fleet``. Every other
    section has a usable default — omit it from the YAML and a
    well-typed default-constructed instance fills in.

    The ``logger`` attribute is a ``LoggerConfig`` instance.

    Methods:
        :meth:`from_yaml`: Load and validate a configuration from a
            YAML file path.
        :meth:`find_resource`: Return the configured
            :class:`ResourceConfig` matching a given resource name, or
            raise :class:`ValueError` listing the configured names.
    """

    credentials: CredentialsConfig
    api: ApiConfig = Field(default_factory=ApiConfig)
    fleet: FleetConfig
    working_directory: Path = Field(default_factory=_default_working_directory)
    output: OutputConfig = Field(default_factory=OutputConfig)
    incremental: IncrementalConfig = Field(default_factory=IncrementalConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    logger: LoggerConfig = Field(default_factory=LoggerConfig)
    resources: tuple[ResourceConfig, ...] = Field(min_length=1)

    @field_validator('working_directory', mode='before')
    @classmethod
    def _expand_and_resolve_working_directory(cls, raw_value: Any) -> Path:
        # ``Any``: Pydantic ``mode='before'`` validators receive arbitrary
        # pre-validation input; the isinstance check below narrows before
        # use.
        """Expand ``~`` and resolve to absolute, without touching disk."""
        if not isinstance(raw_value, (str, Path)):
            raise ValueError(
                f'working_directory must be a string or Path, '
                f'got {type(raw_value).__name__}'
            )
        return Path(raw_value).expanduser().resolve()

    @model_validator(mode='after')
    def _validate_resource_names_unique(self) -> Self:
        """
        Reject duplicate ``name`` entries in ``resources``.

        Two entries with the same ``name`` is almost certainly a user
        mistake (copy-paste or a bad merge) rather than a legitimate
        "run the same pull twice" request. Surfacing it as a config
        error is safer than quietly letting the orchestrator process
        the duplicate.

        Raises:
            ValueError: If any resource name appears more than once.
        """
        seen: set[str] = set()
        duplicates: list[str] = []
        for resource in self.resources:
            if resource.name in seen and resource.name not in duplicates:
                duplicates.append(resource.name)
            seen.add(resource.name)
        if duplicates:
            raise ValueError(
                f'resources contains duplicate name(s): {", ".join(duplicates)}'
            )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """
        Load and validate a pyholman configuration from a YAML file.

        Flow:
            1. Read and parse the YAML file at ``path`` (tilde-expanded,
               resolved to absolute) into a dict.
            2. Read ``HOLMAN_CLIENT_SECRET`` from the environment. Refuse
               to proceed if it is missing or empty.
            3. Refuse to proceed if the YAML already contains
               ``credentials.client_secret`` — the secret belongs in the
               environment, not the file.
            4. Inject the secret into the credentials subdict and hand the
               assembled dict to Pydantic validation.

        Args:
            path: Path to the YAML configuration file. Accepts a ``Path``
                containing ``~`` or a relative path; both are resolved
                against the current working directory before opening.

        Returns:
            A fully validated, frozen ``UserConfig`` instance.

        Raises:
            FileNotFoundError: If ``path`` does not exist. The message
                contains the resolved absolute path.
            RuntimeError: If ``HOLMAN_CLIENT_SECRET`` is unset or empty,
                or if the YAML supplies ``credentials.client_secret``
                (which must come from the environment, never the file).
            pydantic.ValidationError: If any field fails validation.
            ValueError / TypeError: Propagated from ``parse_yaml_to_dict``
                for empty or structurally invalid YAML documents.
        """
        logger.debug('Loading UserConfig from YAML: %s', path)

        raw_config_data: dict[str, Any] = load_yaml_from_path(path)
        credentials_data: dict[str, Any] = cls._extract_credentials_subdict(
            raw_config_data=raw_config_data,
            source_path=path,
        )

        if 'client_secret' in credentials_data:
            raise RuntimeError(
                f'credentials.client_secret must not be set in the YAML '
                f'file (from {path}); it is read from the '
                f'{CLIENT_SECRET_ENV_VAR} environment variable at load '
                f'time to keep secrets out of source control.'
            )

        client_secret: str = cls._read_client_secret_from_env()
        credentials_data['client_secret'] = client_secret

        assembled_data: dict[str, Any] = {
            **raw_config_data,
            'credentials': credentials_data,
        }

        validated_config: Self = cls.model_validate(assembled_data)
        logger.info('Loaded UserConfig from YAML: %s', path)
        return validated_config

    def find_resource(self, resource_name: str) -> ResourceConfig:
        """
        Return the configured resource entry matching ``resource_name``.

        Args:
            resource_name: Registered resource name (e.g.,
                ``'vehicles'``).

        Returns:
            The discriminated-union ``ResourceConfig`` variant present
            in ``self.resources`` with a matching ``name``.

        Raises:
            ValueError: If ``resource_name`` is not present in
                ``self.resources``. The message names the requested
                value and lists the configured resource names so the
                caller can see what is available — same friendly shape
                as :func:`pyholman._endpoints.registry.get_registry_entry`.
        """
        for resource in self.resources:
            if resource.name == resource_name:
                return resource
        configured_names: list[str] = sorted(r.name for r in self.resources)
        raise ValueError(
            f"resource '{resource_name}' is not configured; "
            f'configured resources are: {configured_names}'
        )

    @staticmethod
    def _extract_credentials_subdict(
        raw_config_data: dict[str, Any],
        source_path: Path,
    ) -> dict[str, Any]:
        """
        Return a copy of the ``credentials`` subdict for in-place enrichment.

        A copy — rather than a reference — is returned so the caller can
        inject the client secret without mutating the parsed YAML dict.
        If ``credentials`` is present but not a mapping, the call fails
        loudly; the Pydantic validator would catch it later with a less
        specific message.
        """
        credentials_value: Any = raw_config_data.get('credentials')
        # ``Any``: ``raw_config_data`` is ``dict[str, Any]`` from
        # ``parse_yaml_to_dict`` — each YAML value is arbitrary and
        # narrowed by the isinstance check below.
        if credentials_value is None:
            return {}

        if not isinstance(credentials_value, dict):
            raise TypeError(
                f"'credentials' section in {source_path} must be a mapping, "
                f'got {type(credentials_value).__name__}'
            )

        # Shallow copy is sufficient: we only add one top-level key.
        return dict(credentials_value)

    @staticmethod
    def _read_client_secret_from_env() -> str:
        """Return the client secret from the environment, or raise."""
        raw_secret: str | None = os.environ.get(CLIENT_SECRET_ENV_VAR)
        if not raw_secret:
            raise RuntimeError(
                f'{CLIENT_SECRET_ENV_VAR} environment variable is not set '
                f'or is empty. pyholman reads the Holman API client secret '
                f'from this variable at load time; set it (e.g., export '
                f'{CLIENT_SECRET_ENV_VAR}=...) before loading a UserConfig.'
            )
        return raw_secret
