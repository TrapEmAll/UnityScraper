"""Read/query services for the desktop knowledge browser."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
                    c.source_url, c.source_title,
                    COALESCE(p.priority, 100) source_priority
                FROM knowledge_facts f
                JOIN knowledge_sources s ON s.id = f.source_id
                LEFT JOIN fact_citations c ON c.fact_id = f.id
                LEFT JOIN knowledge_source_priorities p
                    ON p.source_id=f.source_id AND p.property=f.property
                WHERE f.entity_id = ?
                ORDER BY f.property, source_priority, f.confidence DESC, s.name
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
                    c.existing_source_id, c.incoming_source_id,
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

    def list_priorities(self, property_name: str = "") -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id source_id, s.name source_name, p.property,
                       COALESCE(p.priority, 100) priority
                FROM knowledge_sources s
                LEFT JOIN knowledge_source_priorities p ON p.source_id=s.id
                WHERE (?='' OR p.property=?)
                ORDER BY COALESCE(p.property, ''), priority, s.name
                """,
                (property_name, property_name),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_source_priority(
        self, source_id: int, property_name: str, priority: int
    ) -> None:
        property_name = property_name.strip().casefold().replace(" ", "_")
        if not property_name:
            raise ValueError("A fact property is required")
        if not 1 <= priority <= 1000:
            raise ValueError("Priority must be between 1 and 1000")
        with self._connect() as connection:
            source = connection.execute(
                "SELECT id FROM knowledge_sources WHERE id=?", (source_id,)
            ).fetchone()
            if source is None:
                raise KeyError(source_id)
            connection.execute(
                """
                INSERT INTO knowledge_source_priorities(
                    property, source_id, priority, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(property, source_id) DO UPDATE SET
                    priority=excluded.priority, updated_at=excluded.updated_at
                """,
                (
                    property_name,
                    source_id,
                    priority,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        *,
        notes: str = "",
    ) -> dict[str, Any]:
        allowed = {"prefer_existing", "prefer_incoming", "dismiss"}
        if resolution not in allowed:
            raise ValueError(f"Resolution must be one of: {', '.join(sorted(allowed))}")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_conflicts WHERE id=?", (conflict_id,)
            ).fetchone()
            if row is None:
                raise KeyError(conflict_id)
            preferred_value = None
            preferred_source_id = None
            if resolution == "prefer_existing":
                preferred_value = row["existing_value"]
                preferred_source_id = row["existing_source_id"]
            elif resolution == "prefer_incoming":
                preferred_value = row["incoming_value"]
                preferred_source_id = row["incoming_source_id"]
            resolved_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO knowledge_conflict_resolutions(
                    conflict_id, resolution, preferred_value,
                    preferred_source_id, notes, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conflict_id,
                    resolution,
                    preferred_value,
                    preferred_source_id,
                    notes.strip(),
                    resolved_at,
                ),
            )
            connection.execute(
                "UPDATE knowledge_conflicts SET status=? WHERE id=?",
                ("dismissed" if resolution == "dismiss" else "resolved", conflict_id),
            )
            connection.commit()
        return {
            "conflict_id": conflict_id,
            "resolution": resolution,
            "preferred_value": preferred_value,
            "resolved_at": resolved_at,
        }
