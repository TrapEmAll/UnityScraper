"""API application factory adapter for the package layout."""

from __future__ import annotations


def create_api(*args, **kwargs):
    """Create the local REST API without importing Flask at package import time."""
    from api import UnityScraperAPI

    return UnityScraperAPI(*args, **kwargs)


def __getattr__(name: str):
    if name == "UnityScraperAPI":
        from api import UnityScraperAPI

        return UnityScraperAPI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["UnityScraperAPI", "create_api"]
