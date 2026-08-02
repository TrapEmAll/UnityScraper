"""Normalized Xbox 360 knowledge database support.

This module is intentionally source-agnostic.  Adapters extract claims from
ConsoleMods, XenonLibrary, Free60, Redump, No-Intro, or future sources, and the
repository stores those claims with provenance instead of flattening them into
one untraceable metadata blob.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknown game",
    "unknown title",
    "unknown publisher",
    "n/a",
    "none",
    "null",
}


def utc_now() -> str:
    """Return an ISO timestamp suitable for persisted import metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_titleid(value: str) -> str:
    """Normalize an Xbox 360 TitleID or return an empty string."""
    titleid = (value or "").strip().upper()
    if len(titleid) == 8 and all(char in "0123456789ABCDEF" for char in titleid):
        return titleid
    return ""


def is_unknown(value: str | None) -> bool:
    """Return True when a field should be considered safe to enrich."""
    return value is None or value.strip().casefold() in UNKNOWN_VALUES


@dataclass(frozen=True)
class Identifier:
    """A source-attributed identifier attached to an entity."""

    kind: str
    value: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Fact:
    """One claim about an entity, with source context retained."""

    property: str
    value: str
    normalized_value: str = ""
    confidence: float = 1.0
    source_url: str = ""
    source_title: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityRecord:
    """A normalized entity plus its identifiers, names, and facts."""

    entity_type: str
    canonical_name: str
    identifiers: tuple[Identifier, ...] = ()
    names: tuple[str, ...] = ()
    facts: tuple[Fact, ...] = ()


class KnowledgeRepository:
    """Persist normalized source documents, entities, facts, and conflicts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ensure_schema(self) -> None:
        """Create the normalized knowledge schema and supporting indexes."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                homepage_url TEXT,
                license_name TEXT,
                license_url TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                document_type TEXT,
                license_name TEXT,
                fetched_at TEXT,
                http_status INTEGER,
                etag TEXT,
                last_modified TEXT,
                content_sha256 TEXT,
                cache_path TEXT,
                metadata TEXT,
                UNIQUE(source_id, url),
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                revision_key TEXT,
                fetched_at TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                cache_path TEXT,
                metadata TEXT,
                UNIQUE(document_id, content_sha256),
                FOREIGN KEY (document_id) REFERENCES source_documents(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_type, normalized_name)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                source_id INTEGER,
                confidence REAL DEFAULT 1.0,
                UNIQUE(entity_id, normalized_name),
                FOREIGN KEY (entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                source_id INTEGER,
                confidence REAL DEFAULT 1.0,
                UNIQUE(identifier_type, normalized_value, entity_id),
                FOREIGN KEY (entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                property TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                confidence REAL DEFAULT 1.0,
                imported_at TEXT NOT NULL,
                metadata TEXT,
                UNIQUE(entity_id, property, normalized_value, source_id),
                FOREIGN KEY (entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fact_citations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id INTEGER NOT NULL,
                document_id INTEGER,
                revision_id INTEGER,
                source_url TEXT,
                source_title TEXT,
                context TEXT,
                FOREIGN KEY (fact_id) REFERENCES knowledge_facts(id),
                FOREIGN KEY (document_id) REFERENCES source_documents(id),
                FOREIGN KEY (revision_id) REFERENCES source_revisions(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_entity_id INTEGER NOT NULL,
                relationship_type TEXT NOT NULL,
                object_entity_id INTEGER NOT NULL,
                source_id INTEGER,
                confidence REAL DEFAULT 1.0,
                metadata TEXT,
                UNIQUE(subject_entity_id, relationship_type, object_entity_id, source_id),
                FOREIGN KEY (subject_entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (object_entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_slug TEXT NOT NULL,
                adapter_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                records_seen INTEGER DEFAULT 0,
                records_imported INTEGER DEFAULT 0,
                errors TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                property TEXT NOT NULL,
                existing_value TEXT NOT NULL,
                incoming_value TEXT NOT NULL,
                existing_source_id INTEGER,
                incoming_source_id INTEGER,
                detected_at TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                metadata TEXT,
                UNIQUE(entity_id, property, existing_value, incoming_value, incoming_source_id),
                FOREIGN KEY (entity_id) REFERENCES knowledge_entities(id),
                FOREIGN KEY (existing_source_id) REFERENCES knowledge_sources(id),
                FOREIGN KEY (incoming_source_id) REFERENCES knowledge_sources(id)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_identifiers_lookup "
            "ON entity_identifiers(identifier_type, normalized_value)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_facts_lookup "
            "ON knowledge_facts(entity_id, property, confidence DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_entities_type_name "
            "ON knowledge_entities(entity_type, normalized_name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_facts_property "
            "ON knowledge_facts(property)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_citations_fact ON fact_citations(fact_id)"
        )

    def upsert_source(
        self,
        slug: str,
        name: str,
        homepage_url: str = "",
        license_name: str = "",
        license_url: str = "",
        notes: str = "",
    ) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_sources
                (slug, name, homepage_url, license_name, license_url, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                homepage_url = excluded.homepage_url,
                license_name = excluded.license_name,
                license_url = excluded.license_url,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (slug, name, homepage_url, license_name, license_url, notes, utc_now()),
        )
        return int(cursor.execute("SELECT id FROM knowledge_sources WHERE slug = ?", (slug,)).fetchone()[0])

    def upsert_document(
        self,
        source_id: int,
        url: str,
        title: str,
        document_type: str,
        fetched_at: str,
        content_sha256: str,
        cache_path: str,
        http_status: int = 200,
        license_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO source_documents
                (source_id, url, title, document_type, license_name, fetched_at,
                 http_status, content_sha256, cache_path, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, url) DO UPDATE SET
                title = excluded.title,
                document_type = excluded.document_type,
                license_name = excluded.license_name,
                fetched_at = excluded.fetched_at,
                http_status = excluded.http_status,
                content_sha256 = excluded.content_sha256,
                cache_path = excluded.cache_path,
                metadata = excluded.metadata
            """,
            (
                source_id,
                url,
                title,
                document_type,
                license_name,
                fetched_at,
                http_status,
                content_sha256,
                cache_path,
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        document_id = int(
            cursor.execute(
                "SELECT id FROM source_documents WHERE source_id = ? AND url = ?",
                (source_id, url),
            ).fetchone()[0]
        )
        cursor.execute(
            """
            INSERT INTO source_revisions
                (document_id, revision_key, fetched_at, content_sha256, cache_path, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, content_sha256) DO NOTHING
            """,
            (
                document_id,
                content_sha256,
                fetched_at,
                content_sha256,
                cache_path,
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        revision_id = int(
            cursor.execute(
                "SELECT id FROM source_revisions WHERE document_id = ? AND content_sha256 = ?",
                (document_id, content_sha256),
            ).fetchone()[0]
        )
        return document_id, revision_id

    def begin_import_run(self, source_slug: str, adapter_name: str) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_import_runs (source_slug, adapter_name, started_at, status)
            VALUES (?, ?, ?, 'running')
            """,
            (source_slug, adapter_name, utc_now()),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Import run was created without an identifier")
        return cursor.lastrowid

    def finish_import_run(
        self,
        run_id: int,
        status: str,
        records_seen: int,
        records_imported: int,
        errors: Iterable[str] = (),
    ) -> None:
        self.connection.execute(
            """
            UPDATE knowledge_import_runs
            SET finished_at = ?, status = ?, records_seen = ?, records_imported = ?, errors = ?
            WHERE id = ?
            """,
            (utc_now(), status, records_seen, records_imported, json.dumps(list(errors)), run_id),
        )

    def upsert_entity_record(
        self,
        record: EntityRecord,
        source_id: int,
        document_id: int | None = None,
        revision_id: int | None = None,
    ) -> int:
        cursor = self.connection.cursor()
        normalized_name = self._normalize_text(record.canonical_name)
        cursor.execute(
            """
            INSERT INTO knowledge_entities (entity_type, canonical_name, normalized_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(entity_type, normalized_name) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                updated_at = excluded.updated_at
            """,
            (record.entity_type, record.canonical_name, normalized_name, utc_now()),
        )
        entity_id = int(
            cursor.execute(
                """
                SELECT id FROM knowledge_entities
                WHERE entity_type = ? AND normalized_name = ?
                """,
                (record.entity_type, normalized_name),
            ).fetchone()[0]
        )
        names = set(record.names) | {record.canonical_name}
        for name in names:
            if not name:
                continue
            cursor.execute(
                """
                INSERT INTO entity_names
                    (entity_id, name, normalized_name, source_id, confidence)
                VALUES (?, ?, ?, ?, 1.0)
                ON CONFLICT(entity_id, normalized_name) DO NOTHING
                """,
                (entity_id, name, self._normalize_text(name), source_id),
            )
        for identifier in record.identifiers:
            normalized_value = self._normalize_identifier(identifier.kind, identifier.value)
            if not normalized_value:
                continue
            cursor.execute(
                """
                INSERT INTO entity_identifiers
                    (entity_id, identifier_type, identifier_value, normalized_value,
                     source_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(identifier_type, normalized_value, entity_id) DO UPDATE SET
                    confidence = MAX(confidence, excluded.confidence)
                """,
                (
                    entity_id,
                    identifier.kind,
                    identifier.value,
                    normalized_value,
                    source_id,
                    identifier.confidence,
                ),
            )
        for fact in record.facts:
            fact_id = self.upsert_fact(
                entity_id,
                fact,
                source_id,
                document_id=document_id,
                revision_id=revision_id,
            )
            self.record_conflicts(entity_id, fact, source_id)
            if fact_id and (fact.source_url or document_id):
                citation = (
                    fact_id,
                    document_id,
                    revision_id,
                    fact.source_url,
                    fact.source_title,
                    json.dumps(fact.context, sort_keys=True),
                )
                cursor.execute(
                    """
                    INSERT INTO fact_citations
                        (fact_id, document_id, revision_id, source_url, source_title, context)
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM fact_citations
                        WHERE fact_id = ?
                          AND COALESCE(document_id, 0) = COALESCE(?, 0)
                          AND COALESCE(revision_id, 0) = COALESCE(?, 0)
                          AND COALESCE(source_url, '') = COALESCE(?, '')
                    )
                    """,
                    (*citation, fact_id, document_id, revision_id, fact.source_url),
                )
        return entity_id

    def upsert_fact(
        self,
        entity_id: int,
        fact: Fact,
        source_id: int,
        document_id: int | None = None,
        revision_id: int | None = None,
    ) -> int:
        del document_id, revision_id
        normalized_value = fact.normalized_value or self._normalize_text(fact.value)
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_facts
                (entity_id, property, value, normalized_value, source_id,
                 confidence, imported_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id, property, normalized_value, source_id) DO UPDATE SET
                value = excluded.value,
                confidence = MAX(confidence, excluded.confidence),
                imported_at = excluded.imported_at,
                metadata = excluded.metadata
            """,
            (
                entity_id,
                fact.property,
                fact.value,
                normalized_value,
                source_id,
                fact.confidence,
                utc_now(),
                json.dumps(fact.context, sort_keys=True),
            ),
        )
        return int(
            cursor.execute(
                """
                SELECT id FROM knowledge_facts
                WHERE entity_id = ? AND property = ? AND normalized_value = ? AND source_id = ?
                """,
                (entity_id, fact.property, normalized_value, source_id),
            ).fetchone()[0]
        )

    def record_conflicts(self, entity_id: int, fact: Fact, incoming_source_id: int) -> None:
        """Record conflicting source claims without blocking import."""
        normalized_value = fact.normalized_value or self._normalize_text(fact.value)
        cursor = self.connection.cursor()
        rows = cursor.execute(
            """
            SELECT value, normalized_value, source_id
            FROM knowledge_facts
            WHERE entity_id = ? AND property = ? AND normalized_value <> ?
            """,
            (entity_id, fact.property, normalized_value),
        ).fetchall()
        for row in rows:
            cursor.execute(
                """
                INSERT INTO knowledge_conflicts
                    (entity_id, property, existing_value, incoming_value,
                     existing_source_id, incoming_source_id, detected_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, property, existing_value, incoming_value, incoming_source_id)
                DO NOTHING
                """,
                (
                    entity_id,
                    fact.property,
                    row["value"] if isinstance(row, sqlite3.Row) else row[0],
                    fact.value,
                    row["source_id"] if isinstance(row, sqlite3.Row) else row[2],
                    incoming_source_id,
                    utc_now(),
                    json.dumps({"incoming_normalized_value": normalized_value}),
                ),
            )

    def get_entity_by_identifier(
        self,
        identifier_type: str,
        identifier_value: str,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_identifier(identifier_type, identifier_value)
        row = self.connection.execute(
            """
            SELECT e.*
            FROM knowledge_entities AS e
            JOIN entity_identifiers AS i ON i.entity_id = e.id
            WHERE i.identifier_type = ? AND i.normalized_value = ?
            ORDER BY i.confidence DESC
            LIMIT 1
            """,
            (identifier_type, normalized),
        ).fetchone()
        return dict(row) if row else None

    def get_preferred_facts(
        self,
        entity_id: int,
        properties: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        wanted = list(properties)
        if not wanted:
            return {}
        placeholders = ",".join("?" for _ in wanted)
        rows = self.connection.execute(
            f"""
            WITH latest_resolution AS (
                SELECT
                    c.entity_id,
                    c.property,
                    r.preferred_value,
                    r.preferred_source_id
                FROM knowledge_conflict_resolutions AS r
                JOIN knowledge_conflicts AS c ON c.id = r.conflict_id
                WHERE r.resolution IN ('prefer_existing', 'prefer_incoming')
                  AND r.id = (
                      SELECT MAX(newer.id)
                      FROM knowledge_conflict_resolutions AS newer
                      JOIN knowledge_conflicts AS newer_conflict
                        ON newer_conflict.id = newer.conflict_id
                      WHERE newer_conflict.entity_id = c.entity_id
                        AND newer_conflict.property = c.property
                        AND newer.resolution IN (
                            'prefer_existing', 'prefer_incoming'
                        )
                  )
            )
            SELECT
                f.property,
                f.value,
                f.normalized_value,
                f.confidence,
                s.slug AS source_slug,
                s.name AS source_name,
                COALESCE(p.priority, 100) AS source_priority
            FROM knowledge_facts AS f
            JOIN knowledge_sources AS s ON s.id = f.source_id
            LEFT JOIN knowledge_source_priorities AS p
              ON p.source_id = f.source_id AND p.property = f.property
            LEFT JOIN latest_resolution AS resolution
              ON resolution.entity_id = f.entity_id
             AND resolution.property = f.property
            WHERE f.entity_id = ? AND f.property IN ({placeholders})
            ORDER BY
                f.property,
                CASE
                    WHEN resolution.preferred_value = f.value
                     AND (
                         resolution.preferred_source_id IS NULL
                         OR resolution.preferred_source_id = f.source_id
                     )
                    THEN 0
                    ELSE 1
                END,
                source_priority,
                f.confidence DESC,
                f.imported_at DESC
            """,
            (entity_id, *wanted),
        ).fetchall()
        preferred: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row["property"]
            if key not in preferred:
                preferred[key] = dict(row)
        return preferred

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join((value or "").strip().casefold().split())

    @staticmethod
    def _normalize_identifier(identifier_type: str, value: str) -> str:
        if identifier_type == "titleid":
            return normalize_titleid(value)
        return " ".join((value or "").strip().casefold().split())
