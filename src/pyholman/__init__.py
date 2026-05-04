"""pyholman — typed Python client for Holman's Customer Data API."""

from pyholman._endpoints.registry import EndpointName
from pyholman._transport import HolmanError, RateLimitError, TransientHolmanError
from pyholman.fetch import fetch
from pyholman.orchestrator import Orchestrator

__all__: list[str] = [
    'EndpointName',
    'HolmanError',
    'Orchestrator',
    'RateLimitError',
    'TransientHolmanError',
    'fetch',
]
