"""Watched backup folders: periodic inventory scans that report newly added content."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from backup_manager import scan_local_target
from unityscraper.core.paths import DATABASE_PATH
from unityscraper.core.scheduling import ScheduledTask

TitleLookup = Optional[Callable[[str], Optional[str]]]
SCHEDULE_NAME = "watch-folders"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class WatchFolder:
    """One row of ``watch_folders``."""

    id: int
    path: str
    label: str
    enabled: bool
    created_at: str
    last_scan_at: str | None
    last_status: str | None
    last_item_count: int | None
    last_new_count: int | None
    last_error: str | None

    @property
    def display_name(self) -> str:
        return self.label or self.path


@dataclass(frozen=True)
class WatchScanResult:
    """Outcome of scanning one folder; ``new_items`` is empty on the baseline scan."""

    folder: WatchFolder
    new_items: list[dict]
    total_items: int
    removed_count: int


@dataclass(frozen=True)
class WatchScanSummary:
    """Outcome of :meth:`WatchFolderService.scan_all`: successes plus per-folder failures."""

    results: list[WatchScanResult] = field(default_factory=list)
    failures: list[tuple[WatchFolder, str]] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return sum(len(result.new_items) for result in self.results)


class WatchFolderService:
    """Track user folders and diff their backup inventory between scans."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        scanner: Callable[..., Any] | None = None,
    ) -> None:
        from database_migrations import ensure_application_schema

        self.database_path = Path(database_path)
        self.scanner = scanner or scan_local_target
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

    @staticmethod
    def _folder(row: sqlite3.Row) -> WatchFolder:
        values = dict(row)
        values["enabled"] = bool(values["enabled"])
        return WatchFolder(**values)

    def get(self, folder_id: int) -> WatchFolder:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM watch_folders WHERE id=?", (folder_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown watch folder: {folder_id}")
        return self._folder(row)

    def list(self) -> list[WatchFolder]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watch_folders ORDER BY label COLLATE NOCASE, path COLLATE NOCASE"
            ).fetchall()
        return [self._folder(row) for row in rows]

    def add(self, path: str | Path, label: str = "") -> WatchFolder:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Not an existing folder: {resolved}")
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO watch_folders(path, label, created_at) VALUES (?, ?, ?)",
                    (str(resolved), label.strip(), _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Folder is already watched: {resolved}") from exc
        return self.get(int(cursor.lastrowid))

    def remove(self, folder_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM watch_folder_items WHERE folder_id=?", (folder_id,))
            connection.execute("DELETE FROM watch_folders WHERE id=?", (folder_id,))

    def set_enabled(self, folder_id: int, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE watch_folders SET enabled=? WHERE id=?", (int(enabled), folder_id)
            )

    def scan(self, folder_id: int, title_lookup: TitleLookup = None) -> WatchScanResult:
        """Rescan one folder; scanner failures are recorded on the folder and re-raised."""
        folder = self.get(folder_id)
        started = _now()
        try:
            scanned = self.scanner(folder.path, title_lookup=title_lookup)
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE watch_folders SET last_scan_at=?, last_status='failed', last_error=? "
                    "WHERE id=?",
                    (started, str(exc), folder_id),
                )
            raise
        items = {str(item.path): item for item in scanned.items}
        # A folder that never completed a scan records a baseline instead of reporting all as new;
        # baseline items are stamped with the folder's creation time so recent_new_items skips them.
        baseline = folder.last_item_count is None
        first_seen = folder.created_at if baseline else started
        with self._connect() as connection:
            known = {
                row["path"]
                for row in connection.execute(
                    "SELECT path FROM watch_folder_items WHERE folder_id=?", (folder_id,)
                )
            }
            removed = known - items.keys()
            connection.executemany(
                "DELETE FROM watch_folder_items WHERE folder_id=? AND path=?",
                [(folder_id, path) for path in removed],
            )
            new_items = []
            for path, item in items.items():
                record = {
                    "path": path,
                    "titleid": item.title_id or None,
                    "name": item.name or "",
                    "content_type": item.content_type or item.format or None,
                    "size": int(item.size or 0),
                    "first_seen_at": first_seen,
                }
                connection.execute(
                    """
                    INSERT INTO watch_folder_items(
                        folder_id, path, titleid, name, content_type, size,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(folder_id, path) DO UPDATE SET
                        titleid=excluded.titleid, name=excluded.name,
                        content_type=excluded.content_type, size=excluded.size,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (folder_id, path, record["titleid"], record["name"],
                     record["content_type"], record["size"], first_seen, started),
                )
                if not baseline and path not in known:
                    new_items.append(record)
            connection.execute(
                "UPDATE watch_folders SET last_scan_at=?, last_status='ok', last_item_count=?, "
                "last_new_count=?, last_error=NULL WHERE id=?",
                (started, len(items), len(new_items), folder_id),
            )
        return WatchScanResult(self.get(folder_id), new_items, len(items), len(removed))

    def scan_all(self, title_lookup: TitleLookup = None) -> WatchScanSummary:
        """Scan every enabled folder; one failing folder never stops the others."""
        summary = WatchScanSummary()
        for folder in self.list():
            if not folder.enabled:
                continue
            try:
                summary.results.append(self.scan(folder.id, title_lookup))
            except Exception as exc:
                summary.failures.append((folder, str(exc)))
        return summary

    def recent_new_items(self, folder_id: int, limit: int = 100) -> list[dict]:
        """Items discovered after the baseline scan, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item.* FROM watch_folder_items AS item
                JOIN watch_folders AS folder ON folder.id = item.folder_id
                WHERE item.folder_id=? AND item.first_seen_at > folder.created_at
                ORDER BY item.first_seen_at DESC, item.name COLLATE NOCASE
                LIMIT ?
                """,
                (folder_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def schedule(self) -> ScheduledTask:
        return ScheduledTask(
            self.database_path,
            SCHEDULE_NAME,
            default_interval_hours=12,
            min_interval_hours=1,
            default_enabled=True,
        )

    def run_if_due(self, title_lookup: TitleLookup = None) -> WatchScanSummary | None:
        """Run :meth:`scan_all` when the schedule is due; returns ``None`` when skipped."""
        outcome = self.schedule().run_if_due(lambda: self.scan_all(title_lookup))
        return outcome["result"] if outcome else None
