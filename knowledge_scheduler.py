"""App-start knowledge refresh scheduling with persistent, opt-in state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema


TASK_NAME = "knowledge-refresh"
MIN_INTERVAL_HOURS = 6


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeScheduler:
    """Run cached/rate-limited imports when an enabled schedule becomes due."""

    def __init__(self, database_path: str | Path = DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        with self._connect() as connection:
            ensure_application_schema(connection)
            connection.execute(
                """
                INSERT INTO scheduled_sync_state(
                    task_name, enabled, interval_hours, updated_at
                ) VALUES (?, 0, 168, ?)
                ON CONFLICT(task_name) DO NOTHING
                """,
                (TASK_NAME, utc_now().isoformat()),
            )

    @contextmanager
    def _connect(self):
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

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_sync_state WHERE task_name=?", (TASK_NAME,)
            ).fetchone()
        return dict(row) if row else {}

    def configure(self, enabled: bool, interval_hours: int) -> None:
        interval = max(MIN_INTERVAL_HOURS, min(int(interval_hours), 24 * 365))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_sync_state
                SET enabled=?, interval_hours=?, updated_at=?
                WHERE task_name=?
                """,
                (int(enabled), interval, utc_now().isoformat(), TASK_NAME),
            )

    def is_due(self, now: datetime | None = None) -> bool:
        state = self.status()
        if not state or not bool(state["enabled"]):
            return False
        current = now or utc_now()
        completed = _parse_time(state.get("last_completed_at"))
        if completed is None:
            return True
        return current >= completed + timedelta(hours=int(state["interval_hours"]))

    def run_if_due(
        self,
        sync: Callable[[], Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.is_due():
            return None
        operation = sync or _sync_all
        started = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_sync_state
                SET last_started_at=?, last_status='running', last_error=NULL,
                    updated_at=? WHERE task_name=?
                """,
                (started, started, TASK_NAME),
            )
        try:
            result = operation()
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE scheduled_sync_state
                    SET last_status='failed', last_error=?, updated_at=?
                    WHERE task_name=?
                    """,
                    (str(exc), utc_now().isoformat(), TASK_NAME),
                )
            raise
        completed = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_sync_state
                SET last_completed_at=?, last_status='completed',
                    last_error=NULL, updated_at=? WHERE task_name=?
                """,
                (completed, completed, TASK_NAME),
            )
        return {"completed_at": completed, "result": result}


def _sync_all() -> dict[str, Any]:
    from knowledge_sync import sync_consolemods_knowledge, sync_reference_wikis

    return {
        "consolemods": sync_consolemods_knowledge(),
        "wikis": sync_reference_wikis(),
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
