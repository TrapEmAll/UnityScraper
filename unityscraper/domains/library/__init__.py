"""Library and XboxUnity title/update domain."""

from __future__ import annotations

from .catalog import XboxUnityTitleCatalog
from .models import CatalogSyncResult, GameSummary, TitleSuggestion
from .service import LibraryService

__all__ = [
    "CatalogSyncResult",
    "GameSummary",
    "LibraryService",
    "TitleSuggestion",
    "XboxUnityTitleCatalog",
]
