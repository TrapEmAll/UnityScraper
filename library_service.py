"""Compatibility wrapper for the package-owned library service."""

from __future__ import annotations

from unityscraper.domains.library.models import GameSummary
from unityscraper.domains.library.service import LibraryService

__all__ = ["GameSummary", "LibraryService"]
