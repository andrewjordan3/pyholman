# src/pyholman/_core/constants.py
"""
Package-wide constants shared across two or more modules.

Module-local tuning values (HTTP timeouts, backoff multipliers, token
refresh skew, repr-truncation threshold, etc.) stay with their
modules — those values are implementation details of one unit and
duplicating them here would spread the surface area a refactor has
to touch. This file holds only values that are either (1) used in two
or more modules today, or (2) are package-identity concerns that would
change as a unit if we renamed the package or the auth service changed
its endpoint.

Package-private: consumers import from this module directly
(``from pyholman._core.constants import PACKAGE_NAME``). There is no
re-export layer above it.
"""

from typing import Final

__all__: list[str] = [
    'AUTH_ENDPOINT_PATH',
    'BEARER_SCHEME',
    'CLIENT_SECRET_ENV_VAR',
    'PACKAGE_NAME',
]


# Name the package is installed under. Referenced by:
#     - User-Agent construction in ``_transport/factory.py``.
#     - Package-version lookup in ``_storage/metadata/version.py``.
#     - Package logger name in ``_logger/setup.py``.
# Kept as a single constant so a future package rename is one-file.
PACKAGE_NAME: Final[str] = 'pyholman'

# Holman's OAuth2 token endpoint path, relative to ``api.base_url``.
# The same host serves both the token endpoint and the data endpoints,
# so there is no second base URL to configure.
AUTH_ENDPOINT_PATH: Final[str] = '/sso/sts/connect/token'

# OAuth2 scheme string for the ``Authorization`` header. Pyholman only
# supports Bearer tokens; the validator in ``_auth/token_response.py``
# rejects any other ``token_type``, and header construction in
# ``_auth/token_manager.py`` uses this same literal. Centralized so
# the validator and the header builder cannot drift.
BEARER_SCHEME: Final[str] = 'Bearer'

# Environment-variable name the user configuration reads for the
# Holman API client secret. ``UserConfig.from_yaml`` consults it and
# error messages quote it back to the user; every mention is the same
# string.
CLIENT_SECRET_ENV_VAR: Final[str] = 'HOLMAN_CLIENT_SECRET'
