"""Shared infrastructure used across UnityScraper domains."""

from __future__ import annotations

from .metadata import APP_METADATA, AppMetadata
from .version import APP_VERSION, DISPLAY_VERSION

__all__ = ["APP_METADATA", "APP_VERSION", "DISPLAY_VERSION", "AppMetadata"]
