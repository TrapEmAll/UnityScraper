"""High-level knowledge import and enrichment helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from consolemods_adapters import ConsoleModsMultiIdAdapter, ConsoleModsTitleIdAdapter
from dat_adapters import LocalDatAdapter
from database import DatabaseManager
from knowledge_base import KnowledgeRepository
from knowledge_sources import CachedHttpClient, KnowledgeImportService
from wiki_adapters import (
    ConsoleModsWikiAdapter,
    Free60WikiAdapter,
    XenonLibraryWikiAdapter,
)

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


def sync_reference_wikis(
    db: DatabaseManager | None = None,
    cache_dir: Path | str | None = None,
    max_documents_per_source: int | None = None,
) -> dict[str, Any]:
    """Import searchable Xbox 360 wiki articles with per-source isolation."""
    db = db or DatabaseManager()
    client = CachedHttpClient(cache_dir=cache_dir)
    adapters = (
        ConsoleModsWikiAdapter(client, max_documents=max_documents_per_source),
        XenonLibraryWikiAdapter(client, max_documents=max_documents_per_source),
        Free60WikiAdapter(client, max_documents=max_documents_per_source),
    )
    summaries: list[dict[str, Any]] = []

    for adapter in adapters:
        try:
            with db.get_connection() as conn:
                repository = KnowledgeRepository(conn)
                repository.ensure_schema()
                summary = KnowledgeImportService(repository).run_adapter(adapter)
            summaries.append(summary)
        except Exception as exc:
            logger.exception("Knowledge source sync failed: %s", adapter.source.slug)
            summaries.append(
                {
                    "source": adapter.source.slug,
                    "adapter": adapter.adapter_name,
                    "status": "failed",
                    "error": str(exc),
                    "records_imported": 0,
                }
            )
    return {"adapters": summaries}


def import_dat_knowledge(
    path: Path | str,
    source_kind: str,
    db: DatabaseManager | None = None,
) -> dict[str, Any]:
    """Import a user-selected Redump or No-Intro XML DAT."""
    db = db or DatabaseManager()
    adapter = LocalDatAdapter(path, source_kind)
    with db.get_connection() as conn:
        repository = KnowledgeRepository(conn)
        repository.ensure_schema()
        summary = KnowledgeImportService(repository).run_adapter(adapter)
    if summary.get("status") == "failed":
        raise ValueError(str(summary.get("error") or "DAT import failed"))
    return summary
