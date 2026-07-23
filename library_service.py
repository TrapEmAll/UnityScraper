"""
Read-only library queries and archive health checks for the desktop interface.

This module intentionally uses the existing UnityScraper SQLite schema. It does
not perform network requests and can safely be used while browsing the library.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from app_paths import DATABASE_PATH


@dataclass(frozen=True)
class GameSummary:
    """Compact game information displayed in the library list."""

    titleid: str
    name: str
    publisher: str
    last_scraped: str
    covers_total: int
    covers_downloaded: int
    updates_total: int
    updates_downloaded: int
    updates_failed: int


class LibraryService:
    """Provide UI-friendly queries over the existing database."""

    def __init__(self, database_path: Path | str = DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list_games(self, search: str = "") -> list[GameSummary]:
        """Return all games, optionally filtered by title, publisher, or TitleID."""
        if not self.database_path.exists():
            return []

        query = """
            SELECT
                t.titleid,
                COALESCE(NULLIF(t.name, ''), t.titleid) AS name,
                COALESCE(t.publisher, '') AS publisher,
                COALESCE(t.last_scraped, '') AS last_scraped,
                COUNT(DISTINCT c.id) AS covers_total,
                COUNT(DISTINCT CASE WHEN c.status = 'downloaded' THEN c.id END)
                    AS covers_downloaded,
                COUNT(DISTINCT u.id) AS updates_total,
                COUNT(DISTINCT CASE WHEN u.status = 'downloaded' THEN u.id END)
                    AS updates_downloaded,
                COUNT(DISTINCT CASE WHEN u.status = 'failed' THEN u.id END)
                    AS updates_failed
            FROM titleids AS t
            LEFT JOIN covers AS c ON c.titleid = t.titleid
            LEFT JOIN title_updates AS u ON u.titleid = t.titleid
        """
        parameters: list[Any] = []

        if search.strip():
            query += """
                WHERE LOWER(t.titleid) LIKE ?
                   OR LOWER(COALESCE(t.name, '')) LIKE ?
                   OR LOWER(COALESCE(t.publisher, '')) LIKE ?
            """
            value = f"%{search.strip().lower()}%"
            parameters.extend([value, value, value])

        query += """
            GROUP BY t.titleid, t.name, t.publisher, t.last_scraped
            ORDER BY name COLLATE NOCASE, t.titleid
        """

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            GameSummary(
                titleid=row["titleid"],
                name=row["name"],
                publisher=row["publisher"],
                last_scraped=row["last_scraped"],
                covers_total=row["covers_total"],
                covers_downloaded=row["covers_downloaded"],
                updates_total=row["updates_total"],
                updates_downloaded=row["updates_downloaded"],
                updates_failed=row["updates_failed"],
            )
            for row in rows
        ]

    def get_game_details(self, titleid: str) -> dict[str, Any]:
        """Return one title and all of its cover/update records."""
        if not self.database_path.exists():
            return {}

        with self._connect() as connection:
            title = connection.execute(
                "SELECT * FROM titleids WHERE titleid = ?",
                (titleid,),
            ).fetchone()

            if title is None:
                return {}

            covers = connection.execute(
                """
                SELECT *
                FROM covers
                WHERE titleid = ?
                ORDER BY
                    CASE status
                        WHEN 'downloaded' THEN 0
                        WHEN 'pending' THEN 1
                        ELSE 2
                    END,
                    download_date DESC
                """,
                (titleid,),
            ).fetchall()

            updates = connection.execute(
                """
                SELECT *
                FROM title_updates
                WHERE titleid = ?
                ORDER BY media_id, CAST(version AS INTEGER) DESC, version DESC
                """,
                (titleid,),
            ).fetchall()

        return {
            "title": dict(title),
            "covers": [dict(row) for row in covers],
            "updates": [dict(row) for row in updates],
        }

    def get_dashboard_counts(self) -> dict[str, int]:
        """Return summary counts used by the dashboard header."""
        if not self.database_path.exists():
            return {
                "games": 0,
                "updates_available": 0,
                "updates_downloaded": 0,
                "failed": 0,
                "covers_downloaded": 0,
            }

        sql = {
            "games": "SELECT COUNT(*) FROM titleids",
            "updates_available": "SELECT COUNT(*) FROM title_updates",
            "updates_downloaded": (
                "SELECT COUNT(*) FROM title_updates WHERE status = 'downloaded'"
            ),
            "failed": """
                SELECT
                    (SELECT COUNT(*) FROM title_updates WHERE status = 'failed') +
                    (SELECT COUNT(*) FROM covers WHERE status = 'failed')
            """,
            "covers_downloaded": (
                "SELECT COUNT(*) FROM covers WHERE status = 'downloaded'"
            ),
        }

        with self._connect() as connection:
            return {
                name: int(connection.execute(statement).fetchone()[0] or 0)
                for name, statement in sql.items()
            }

    def find_database_duplicates(self) -> list[dict[str, Any]]:
        """
        Find duplicate logical records.

        Title updates are grouped by TitleID, MediaID, and version. Covers are
        grouped by TitleID and URL because the existing schema does not enforce
        a unique cover constraint.
        """
        if not self.database_path.exists():
            return []

        with self._connect() as connection:
            update_rows = connection.execute(
                """
                SELECT
                    'update' AS item_type,
                    titleid,
                    COALESCE(media_id, '') AS identity_a,
                    COALESCE(version, '') AS identity_b,
                    COUNT(*) AS duplicate_count
                FROM title_updates
                GROUP BY titleid, media_id, version
                HAVING COUNT(*) > 1
                """
            ).fetchall()

            cover_rows = connection.execute(
                """
                SELECT
                    'cover' AS item_type,
                    titleid,
                    COALESCE(cover_url, '') AS identity_a,
                    '' AS identity_b,
                    COUNT(*) AS duplicate_count
                FROM covers
                GROUP BY titleid, cover_url
                HAVING COUNT(*) > 1
                """
            ).fetchall()

        return [dict(row) for row in (*update_rows, *cover_rows)]

    def scan_archive_health(self) -> dict[str, Any]:
        """Check downloaded database records for missing, empty, and duplicate files."""
        report: dict[str, Any] = {
            "checked": 0,
            "healthy": [],
            "missing": [],
            "empty": [],
            "duplicate_files": [],
            "database_duplicates": self.find_database_duplicates(),
        }

        if not self.database_path.exists():
            return report

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT 'cover' AS item_type, id, titleid, file_path, file_size
                FROM covers
                WHERE status = 'downloaded'
                UNION ALL
                SELECT 'update' AS item_type, id, titleid, file_path, file_size
                FROM title_updates
                WHERE status = 'downloaded'
                """
            ).fetchall()

        hashes: dict[str, list[dict[str, Any]]] = {}

        for row in rows:
            item = dict(row)
            report["checked"] += 1
            raw_path = item.get("file_path")

            if not raw_path:
                report["missing"].append({**item, "reason": "No file path stored"})
                continue

            path = Path(raw_path)
            if not path.exists():
                report["missing"].append({**item, "reason": "File does not exist"})
                continue

            size = path.stat().st_size
            if size == 0:
                report["empty"].append({**item, "actual_size": 0})
                continue

            digest = self._sha256(path)
            hashes.setdefault(digest, []).append(
                {**item, "actual_size": size, "sha256": digest}
            )
            report["healthy"].append({**item, "actual_size": size, "sha256": digest})

        report["duplicate_files"] = [
            {"sha256": digest, "items": items}
            for digest, items in hashes.items()
            if len(items) > 1
        ]
        return report

    @staticmethod
    def _sha256(path: Path) -> str:
        """Calculate SHA-256 without loading the complete file into memory."""
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
