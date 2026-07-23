"""High-level knowledge import and enrichment helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from consolemods_adapters import ConsoleModsMultiIdAdapter, ConsoleModsTitleIdAdapter
from database import DatabaseManager
from knowledge_base import KnowledgeRepository
from knowledge_sources import CachedHttpClient, KnowledgeImportService

logger = logging.getLogger(__name__)


def sync_consolemods_knowledge(
    db: DatabaseManager | None = None,
    cache_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Import ConsoleMods TitleID and Multi-ID data, then enrich the library."""
    db = db or DatabaseManager()
    summaries: list[dict[str, int | str]] = []

    with db.get_connection() as conn:
        repository = KnowledgeRepository(conn)
        repository.ensure_schema()
        service = KnowledgeImportService(repository)
        client = CachedHttpClient(cache_dir=cache_dir)

        for adapter in (
            ConsoleModsTitleIdAdapter(client),
            ConsoleModsMultiIdAdapter(client),
        ):
            summary = service.run_adapter(adapter)
            summaries.append(summary)
            logger.info(
                "Imported %s records from %s",
                summary["records_imported"],
                summary["adapter"],
            )

    enriched = db.enrich_existing_titleids_from_knowledge()
    return {
        "adapters": summaries,
        "titleids_enriched": enriched,
    }
