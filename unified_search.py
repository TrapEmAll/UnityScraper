"""Fast, local search across UnityScraper's library and knowledge domains."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema


@dataclass(frozen=True)
class SearchResult:
    category: str
    title: str
    subtitle: str
    identifier: str
    target: str
    score: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnifiedSearchService:
    """Query every user-facing domain without requiring a network request."""

    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            ensure_application_schema(connection)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def search(
        self,
        query: str,
        *,
        categories: Iterable[str] = (),
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        needle = " ".join(query.strip().split())
        if len(needle) < 2:
            return []
        wanted = {item.casefold() for item in categories}
        term = f"%{needle}%"
        results: list[SearchResult] = []
        with self._connect() as connection:
            if not wanted or "game" in wanted:
                results.extend(self._games(connection, needle, term))
            if not wanted or "knowledge" in wanted:
                results.extend(self._knowledge(connection, needle, term))
            if not wanted or "profile" in wanted:
                results.extend(self._profiles(connection, term))
            if not wanted or "save" in wanted:
                results.extend(self._saves(connection, term))
            if not wanted or "achievement" in wanted:
                results.extend(self._achievements(connection, term))
            if not wanted or "file" in wanted:
                results.extend(self._files(connection, term))
            if not wanted or "tool" in wanted:
                results.extend(self._structured(connection, term))
        unique: dict[tuple[str, str], SearchResult] = {}
        for result in results:
            key = (result.category, result.target)
            previous = unique.get(key)
            if previous is None or result.score > previous.score:
                unique[key] = result
        ordered = sorted(
            unique.values(), key=lambda row: (-row.score, row.title.casefold(), row.category)
        )
        return [item.to_dict() for item in ordered[: max(1, min(limit, 500))]]

    @staticmethod
    def _rank(needle: str, title: str, identifier: str = "") -> int:
        query = needle.casefold()
        name = title.casefold()
        key = identifier.casefold()
        if query == key or query == name:
            return 100
        if name.startswith(query) or key.startswith(query):
            return 80
        return 50

    def _games(self, connection, needle: str, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT titleid, name, COALESCE(publisher, '') publisher
            FROM titleids
            WHERE titleid LIKE ? OR name LIKE ? OR publisher LIKE ?
            UNION
            SELECT titleid, name, '' publisher FROM xboxunity_title_catalog
            WHERE titleid LIKE ? OR name LIKE ?
            LIMIT 200
            """,
            (term, term, term, term, term),
        ).fetchall()
        return [
            SearchResult(
                "game",
                row["name"] or row["titleid"],
                " | ".join(value for value in (row["titleid"], row["publisher"]) if value),
                row["titleid"],
                f"game:{row['titleid']}",
                self._rank(needle, row["name"] or "", row["titleid"]),
            )
            for row in rows
        ]

    def _knowledge(self, connection, needle: str, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT DISTINCT e.id, e.entity_type, e.canonical_name,
                   GROUP_CONCAT(DISTINCT i.identifier_value) identifiers
            FROM knowledge_entities e
            LEFT JOIN entity_identifiers i ON i.entity_id=e.id
            LEFT JOIN knowledge_facts f ON f.entity_id=e.id
            WHERE e.canonical_name LIKE ? OR i.identifier_value LIKE ? OR f.value LIKE ?
            GROUP BY e.id LIMIT 200
            """,
            (term, term, term),
        ).fetchall()
        return [
            SearchResult(
                "knowledge",
                row["canonical_name"],
                f"{row['entity_type']} | {row['identifiers'] or 'source-attributed record'}",
                str(row["id"]),
                f"knowledge:{row['id']}",
                self._rank(needle, row["canonical_name"], row["identifiers"] or ""),
            )
            for row in rows
        ]

    @staticmethod
    def _profiles(connection, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT profile_id, COALESCE(gamertag, 'Unknown gamertag') gamertag,
                   source_path FROM xbox_profiles
            WHERE profile_id LIKE ? OR gamertag LIKE ? OR source_path LIKE ?
            LIMIT 100
            """,
            (term, term, term),
        ).fetchall()
        return [
            SearchResult("profile", row["gamertag"], row["profile_id"], row["profile_id"],
                         f"profile:{row['profile_id']}", 60)
            for row in rows
        ]

    @staticmethod
    def _saves(connection, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT id, titleid, name, profile_id, source_path FROM profile_saves
            WHERE titleid LIKE ? OR name LIKE ? OR profile_id LIKE ? OR source_path LIKE ?
            LIMIT 150
            """,
            (term, term, term, term),
        ).fetchall()
        return [
            SearchResult("save", row["name"], f"{row['titleid']} | {row['profile_id']}",
                         str(row["id"]), f"save:{row['id']}", 55)
            for row in rows
        ]

    @staticmethod
    def _achievements(connection, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT a.id, a.title, a.gamerscore, a.unlock_state, g.titleid
            FROM profile_achievements a
            JOIN profile_gpd_files g ON g.id=a.gpd_file_id
            WHERE a.title LIKE ? OR a.locked_description LIKE ?
               OR a.unlocked_description LIKE ? OR g.titleid LIKE ?
            LIMIT 150
            """,
            (term, term, term, term),
        ).fetchall()
        return [
            SearchResult("achievement", row["title"] or "Untitled achievement",
                         f"{row['titleid']} | {row['gamerscore']}G | {row['unlock_state']}",
                         str(row["id"]), f"achievement:{row['id']}", 50)
            for row in rows
        ]

    @staticmethod
    def _files(connection, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT id, path, size, COALESCE(sha256, '') sha256 FROM local_file_hashes
            WHERE path LIKE ? OR sha256 LIKE ? ORDER BY calculated_at DESC LIMIT 100
            """,
            (term, term),
        ).fetchall()
        return [
            SearchResult("file", Path(row["path"]).name, row["path"], str(row["id"]),
                         f"file:{row['path']}", 40)
            for row in rows
        ]

    @staticmethod
    def _structured(connection, term: str) -> list[SearchResult]:
        rows = connection.execute(
            """
            SELECT id, record_type, canonical_name, properties_json
            FROM structured_knowledge_records
            WHERE canonical_name LIKE ? OR properties_json LIKE ? LIMIT 150
            """,
            (term, term),
        ).fetchall()
        return [
            SearchResult(row["record_type"], row["canonical_name"], "Structured knowledge",
                         str(row["id"]), f"structured:{row['id']}", 45)
            for row in rows
        ]
