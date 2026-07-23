"""Read/query services for the desktop knowledge browser."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app_paths import DATABASE_PATH
from consolemods_adapters import CONSOLEMODS_SOURCE
from dat_adapters import NOINTRO_SOURCE, REDUMP_SOURCE
from database import DatabaseManager
from knowledge_base import KnowledgeRepository
from wiki_adapters import (
    CONSOLEMODS_WIKI_SOURCE,
    FREE60_SOURCE,
    XENONLIBRARY_SOURCE,
)


class KnowledgeService:
    """Provide UI-friendly access to normalized knowledge and provenance."""

    def __init__(self, database_path: Path | str = DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        database = DatabaseManager(str(self.database_path))
        with database.get_connection() as connection:
            repository = KnowledgeRepository(connection)
            for source in (
                CONSOLEMODS_SOURCE,
                CONSOLEMODS_WIKI_SOURCE,
                XENONLIBRARY_SOURCE,
                FREE60_SOURCE,
                REDUMP_SOURCE,
                NOINTRO_SOURCE,
            ):
                repository.upsert_source(
                    source.slug,
                    source.name,
                    homepage_url=source.homepage_url,
                    license_name=source.license_name,
                    license_url=source.license_url,
                    notes=source.notes,
                )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            statements = {
                "entities": "SELECT COUNT(*) FROM knowledge_entities",
                "facts": "SELECT COUNT(*) FROM knowledge_facts",
                "documents": "SELECT COUNT(*) FROM source_documents",
                "sources": "SELECT COUNT(*) FROM knowledge_sources",
                "conflicts": (
                    "SELECT COUNT(*) FROM knowledge_conflicts WHERE status = 'open'"
                ),
            }
            return {
                key: int(connection.execute(sql).fetchone()[0] or 0)
                for key, sql in statements.items()
            }

    def search(
        self,
        query: str = "",
        entity_type: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        parameters: list[Any] = []
        where: list[str] = []
        if query.strip():
            value = f"%{query.strip().casefold()}%"
            where.append(
                """
                (
                    LOWER(e.canonical_name) LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM entity_identifiers i
                        WHERE i.entity_id = e.id AND LOWER(i.identifier_value) LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM knowledge_facts f
                        WHERE f.entity_id = e.id AND LOWER(f.value) LIKE ?
                    )
                )
                """
            )
            parameters.extend((value, value, value))
        if entity_type:
            where.append("e.entity_type = ?")
            parameters.append(entity_type)

        sql = """
            SELECT
                e.id,
                e.entity_type,
                e.canonical_name,
                COUNT(DISTINCT f.id) AS fact_count,
                COUNT(DISTINCT f.source_id) AS source_count,
                GROUP_CONCAT(DISTINCT i.identifier_value) AS identifiers
            FROM knowledge_entities e
            LEFT JOIN entity_identifiers i ON i.entity_id = e.id
            LEFT JOIN knowledge_facts f ON f.entity_id = e.id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += """
            GROUP BY e.id, e.entity_type, e.canonical_name
            ORDER BY e.canonical_name COLLATE NOCASE
            LIMIT ?
        """
        parameters.append(max(1, min(limit, 5000)))
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    def entity_details(self, entity_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            entity = connection.execute(
                "SELECT * FROM knowledge_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if entity is None:
                return {}
            identifiers = connection.execute(
                """
                SELECT i.identifier_type, i.identifier_value, i.confidence, s.name source_name
                FROM entity_identifiers i
                LEFT JOIN knowledge_sources s ON s.id = i.source_id
                WHERE i.entity_id = ?
                ORDER BY i.identifier_type, i.identifier_value
                """,
                (entity_id,),
            ).fetchall()
            facts = connection.execute(
                """
                SELECT
                    f.id, f.property, f.value, f.confidence,
                    s.name source_name, s.homepage_url,
                    c.source_url, c.source_title
                FROM knowledge_facts f
                JOIN knowledge_sources s ON s.id = f.source_id
                LEFT JOIN fact_citations c ON c.fact_id = f.id
                WHERE f.entity_id = ?
                ORDER BY f.property, f.confidence DESC, s.name
                """,
                (entity_id,),
            ).fetchall()
        return {
            "entity": dict(entity),
            "identifiers": [dict(row) for row in identifiers],
            "facts": [dict(row) for row in facts],
        }

    def list_sources(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.*,
                    COUNT(DISTINCT d.id) document_count,
                    COUNT(DISTINCT f.id) fact_count,
                    MAX(r.finished_at) last_sync,
                    (
                        SELECT r2.status
                        FROM knowledge_import_runs r2
                        WHERE r2.source_slug = s.slug
                        ORDER BY r2.id DESC LIMIT 1
                    ) last_status
                FROM knowledge_sources s
                LEFT JOIN source_documents d ON d.source_id = s.id
                LEFT JOIN knowledge_facts f ON f.source_id = s.id
                LEFT JOIN knowledge_import_runs r ON r.source_slug = s.slug
                GROUP BY s.id
                ORDER BY s.name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_import_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_import_runs
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_conflicts(self, status: str = "open") -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id, c.property, c.existing_value, c.incoming_value,
                    c.detected_at, c.status, e.canonical_name,
                    old.name existing_source, new.name incoming_source
                FROM knowledge_conflicts c
                JOIN knowledge_entities e ON e.id = c.entity_id
                LEFT JOIN knowledge_sources old ON old.id = c.existing_source_id
                LEFT JOIN knowledge_sources new ON new.id = c.incoming_source_id
                WHERE (? = '' OR c.status = ?)
                ORDER BY c.detected_at DESC
                """,
                (status, status),
            ).fetchall()
        return [dict(row) for row in rows]
