"""Persistent interval schedules stored in ``scheduled_sync_state``."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ScheduledTask:
    """One named task that runs at most once per interval while enabled."""

    def __init__(
        self,
        database_path: str | Path,
        task_name: str,
        *,
        default_interval_hours: int = 168,
        min_interval_hours: int = 1,
        default_enabled: bool = False,
    ) -> None:
        from database_migrations import ensure_application_schema

        self.database_path = Path(database_path)
        self.task_name = task_name
        self.min_interval_hours = min_interval_hours
        with self._connect() as connection:
            ensure_application_schema(connection)
            connection.execute(
                """
                INSERT INTO scheduled_sync_state(
                    task_name, enabled, interval_hours, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(task_name) DO NOTHING
                """,
                (
                    task_name,
                    int(default_enabled),
                    self._clamp(default_interval_hours),
                    utc_now().isoformat(),
                ),
            )

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

    def _clamp(self, interval_hours: int) -> int:
        return max(self.min_interval_hours, min(int(interval_hours), 24 * 365))

    def _update(self, assignments: str, *values: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                f"UPDATE scheduled_sync_state SET {assignments}, updated_at=? WHERE task_name=?",
                (*values, utc_now().isoformat(), self.task_name),
            )

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_sync_state WHERE task_name=?", (self.task_name,)
            ).fetchone()
        return dict(row) if row else {}

    def configure(self, enabled: bool, interval_hours: int) -> None:
        self._update("enabled=?, interval_hours=?", int(enabled), self._clamp(interval_hours))

    def is_due(self, now: datetime | None = None) -> bool:
        state = self.status()
        if not state or not bool(state["enabled"]):
            return False
        completed = parse_time(state.get("last_completed_at"))
        if completed is None:
            return True
        return (now or utc_now()) >= completed + timedelta(hours=int(state["interval_hours"]))

    def run(self, operation: Callable[[], Any]) -> dict[str, Any]:
        """Run now, recording start, completion, or failure; failures re-raise."""
        self._update("last_started_at=?, last_status='running', last_error=NULL", utc_now().isoformat())
        try:
            result = operation()
        except Exception as exc:
            self._update("last_status='failed', last_error=?", str(exc))
            raise
        completed = utc_now().isoformat()
        self._update("last_completed_at=?, last_status='completed', last_error=NULL", completed)
        return {"completed_at": completed, "result": result}

    def run_if_due(self, operation: Callable[[], Any]) -> dict[str, Any] | None:
        return self.run(operation) if self.is_due() else None
