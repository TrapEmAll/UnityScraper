"""Source-attributed knowledge and offline reference domain."""

from __future__ import annotations

from .models import EntityRecord, Fact, Identifier
from .repository import KnowledgeRepository, is_unknown, normalize_titleid
from .service import KnowledgeService

__all__ = [
    "EntityRecord",
    "Fact",
    "Identifier",
    "KnowledgeRepository",
    "KnowledgeService",
    "is_unknown",
    "normalize_titleid",
]
