# src/pyholman/_config/retry.py
"""Retry-policy section of the user configuration."""

from pydantic import Field

from pyholman._core import FrozenModel

__all__: list[str] = ['RetryConfig']


class RetryConfig(FrozenModel):
    """
    Policy for retrying transient HTTP failures against the Holman API.

    Only the two knobs that legitimately differ per deployment live here.
    The exponential-backoff multiplier and the small buffer added to
    server-supplied Retry-After values are internal tuning and stay as
    module constants in ``_transport/retry.py``.

    Attributes:
        max_attempts: Total attempts including the initial try. A value
            of ``1`` disables retries; the default of ``5`` allows four
            retries after the first attempt, which is conservative enough
            to ride out short Holman or corporate-proxy hiccups without
            masking a real outage for long.
        backoff_max_seconds: Upper bound on the exponential wait between
            retries. The wait grows as ``2 ** (attempt - 1)`` seconds and
            is then clamped to this cap, so the worst-case wall time for
            a run stays bounded on later attempts.
    """

    max_attempts: int = Field(default=5, ge=1)
    backoff_max_seconds: float = Field(default=60.0, gt=0)
