"""Persistent in-app notification history."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from unityscraper.core.paths import DATABASE_PATH

LEVELS = ("info", "success", "warning", "error")
HISTORY_LIMIT = 500


@dataclass(frozen=True)
class Notification:
    id: int
    level: str
    title: str
    message: str
    source: str
    created_at: str
    read: bool


class NotificationService:
    """Store notifications and keep the newest ``HISTORY_LIMIT`` entries."""

    def __init__(self, database_path: str | Path = DATABASE_PATH) -> None:
        from database_migrations import ensure_application_schema

        self.database_path = Path(database_path)
        with self._connect() as connection:
            ensure_application_schema(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add(self, level: str, title: str, message: str = "", source: str = "") -> Notification:
        if level not in LEVELS:
            raise ValueError(f"Unknown notification level: {level}")
        created = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO notifications(level, title, message, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (level, title, message, source, created),
            )
            connection.execute(
                "DELETE FROM notifications WHERE id NOT IN "
                "(SELECT id FROM notifications ORDER BY id DESC LIMIT ?)",
                (HISTORY_LIMIT,),
            )
        return Notification(int(cursor.lastrowid), level, title, message, source, created, False)

    def recent(self, limit: int = 50) -> list[Notification]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Notification(
                row["id"], row["level"], row["title"], row["message"], row["source"],
                row["created_at"], row["read_at"] is not None,
            )
            for row in rows
        ]

    def unread_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
                ).fetchone()[0]
            )

    def mark_all_read(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE notifications SET read_at=? WHERE read_at IS NULL",
                (datetime.now(timezone.utc).isoformat(),),
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM notifications")
