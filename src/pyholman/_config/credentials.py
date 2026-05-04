# src/pyholman/_config/credentials.py
"""Holman API credentials section of the user configuration."""

from pydantic import SecretStr

from pyholman._core import FrozenModel

__all__: list[str] = ['CredentialsConfig']


class CredentialsConfig(FrozenModel):
    """
    Holman API credentials.

    The ``client_id`` is a non-secret identifier that lives in the user's
    YAML configuration. The ``client_secret`` is read from the
    ``HOLMAN_CLIENT_SECRET`` environment variable by ``UserConfig.from_yaml``
    and injected into this model at validation time — it is deliberately
    absent from the YAML schema so it cannot be committed to source control.

    The secret is stored as ``pydantic.SecretStr`` so its value does not
    appear in ``repr()`` or log output. Callers must call
    ``.get_secret_value()`` to read the underlying string.
    """

    client_id: str
    client_secret: SecretStr
