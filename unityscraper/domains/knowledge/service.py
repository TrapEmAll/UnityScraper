"""Package-facing knowledge service exports."""

from __future__ import annotations

from knowledge_service import KnowledgeService

from .models import EntityRecord, Fact, Identifier
from .repository import KnowledgeRepository, is_unknown, normalize_titleid

__all__ = [
    "EntityRecord",
    "Fact",
    "Identifier",
    "KnowledgeRepository",
    "KnowledgeService",
    "is_unknown",
    "normalize_titleid",
]
