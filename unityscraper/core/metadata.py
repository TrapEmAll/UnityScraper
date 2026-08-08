"""Application metadata shared by every surface."""

from __future__ import annotations

from dataclasses import dataclass

from .paths import APP_NAME, APP_SLUG
from .version import APP_VERSION, DISPLAY_VERSION


@dataclass(frozen=True)
class AppMetadata:
    """Stable metadata for UI, CLI, API, packaging, and diagnostics."""

    name: str
    slug: str
    version: str
    display_version: str


APP_METADATA = AppMetadata(
    name=APP_NAME,
    slug=APP_SLUG,
    version=APP_VERSION,
    display_version=DISPLAY_VERSION,
)

__all__ = ["APP_METADATA", "AppMetadata"]
