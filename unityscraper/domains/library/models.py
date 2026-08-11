"""Library and catalog data models."""

from __future__ import annotations

from dataclasses import dataclass

from title_catalog import CatalogSyncResult, TitleSuggestion


@dataclass(frozen=True)
class GameSummary:
    """Compact game information displayed in the library list."""

    titleid: str
    name: str
    publisher: str
    last_scraped: str
    covers_total: int
    covers_downloaded: int
    updates_total: int
    updates_downloaded: int
    updates_failed: int


__all__ = ["CatalogSyncResult", "GameSummary", "TitleSuggestion"]
