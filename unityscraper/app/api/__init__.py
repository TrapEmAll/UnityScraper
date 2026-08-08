"""Local REST API application adapters."""

from __future__ import annotations

from .entrypoint import create_api

__all__ = ["UnityScraperAPI", "create_api"]


def __getattr__(name: str):
    if name == "UnityScraperAPI":
        from .entrypoint import UnityScraperAPI

        return UnityScraperAPI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
