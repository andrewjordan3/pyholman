# src/pyholman/_client/__init__.py
"""Internal high-level client for Holman's Customer Data API."""

from pyholman._client.client import HolmanClient

__all__: list[str] = ['HolmanClient']
