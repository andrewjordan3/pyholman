# src/pyholman/_transport/transport.py
"""
Bundle an :class:`httpx.Client` with the retry policy and clock applied to
each send.

``HttpTransport`` is a pure container — no methods, no behavior. The
behavior lives in :func:`pyholman._transport.send_request`, which reads
the fields off a single parameter. Bundling fields that always travel
together matches ``CLAUDE.md``'s rule on parameters that appear in
lockstep across call sites: ``send_request(transport, request)`` rather
than ``send_request(client, request, retry_config, clock)``, and callers
(TokenManager, HolmanClient) store one attribute instead of three.
"""

from dataclasses import dataclass

import httpx

from pyholman._clock import Clock
from pyholman._config import RetryConfig

__all__: list[str] = ['HttpTransport']


@dataclass(frozen=True, slots=True)
class HttpTransport:
    """
    The transport pyholman callers use to talk to the Holman API.

    Attributes:
        client: A configured ``httpx.Client``. The caller owns its
            lifetime; typically constructed via
            :func:`pyholman._transport.build_transport` and held as an
            instance attribute for the duration of a run.
        retry_config: Retry policy applied by ``send_request`` on every
            call made through this transport. Lives on the transport
            (rather than being passed per-call) because every call site
            uses the same policy — it is a property of the deployment,
            not of the individual request.
        clock: Time provider used by code paths that need wall-clock or
            monotonic time (token-expiry checks, ``Retry-After``
            HTTP-date arithmetic, future per-resource timing). Lives on
            the transport so a test can construct a deterministic
            :class:`~pyholman._clock.FrozenClock` once and have every
            time-dependent helper read from it.
    """

    client: httpx.Client
    retry_config: RetryConfig
    clock: Clock
