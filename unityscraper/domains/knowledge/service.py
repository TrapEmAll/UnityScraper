"""Package-facing knowledge service exports."""

from __future__ import annotations

from knowledge_base import KnowledgeRepository, is_unknown
from knowledge_service import KnowledgeService

__all__ = ["KnowledgeRepository", "KnowledgeService", "is_unknown"]

