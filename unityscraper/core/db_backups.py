"""Automatic and manual SQLite database backups with retention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from database_migrations import create_database_backup, restore_database_backup
from unityscraper.core.config import read_config, update_config
from unityscraper.core.paths import CONFIG_PATH, DATA_DIR, DATABASE_PATH
from unityscraper.core.scheduling import ScheduledTask

TASK_NAME = "database-backup"
KEEP_CONFIG_KEY = "database_backup_keep"
DEFAULT_KEEP = 7
KEEP_RANGE = (1, 100)
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_NAME_PATTERN = re.compile(r"^unityscraper-(\d{8}-\d{6})-(auto|manual)\.db$")


@dataclass(frozen=True)
class BackupInfo:
    """One backup file in the backup folder."""

    path: Path
    created_at: datetime
    size: int
    automatic: bool


def clamp_keep(value: object) -> int:
    """Return ``value`` as a retention count within ``KEEP_RANGE``; junk becomes the default."""
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        number = DEFAULT_KEEP
    return max(KEEP_RANGE[0], min(KEEP_RANGE[1], number))


class AutoBackupService:
    """Create, list, prune and restore database backups; automatic runs follow a schedule."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        backup_dir: str | Path | None = None,
        config_path: Path = CONFIG_PATH,
    ) -> None:
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir) if backup_dir else DATA_DIR / "backups"
        self.config_path = config_path
        self.schedule = ScheduledTask(
            self.database_path,
            TASK_NAME,
            default_interval_hours=24,
            min_interval_hours=1,
            default_enabled=True,
        )

    def create(self, automatic: bool = False) -> BackupInfo:
        kind = "auto" if automatic else "manual"
        stamp = datetime.now().replace(microsecond=0)
        target = self._target(stamp, kind)
        while target.exists():  # Same-second backups move to the next free second.
            stamp += timedelta(seconds=1)
            target = self._target(stamp, kind)
        # Write beside the target first so a crash never leaves a half-written listed backup.
        partial = target.with_name(target.name + ".partial")
        create_database_backup(self.database_path, partial)
        partial.replace(target)
        return BackupInfo(target, stamp, target.stat().st_size, automatic)

    def _target(self, stamp: datetime, kind: str) -> Path:
        return self.backup_dir / f"unityscraper-{stamp.strftime(_STAMP_FORMAT)}-{kind}.db"

    def list(self) -> list[BackupInfo]:
        """Backups newest first; files that do not follow the naming pattern are ignored."""
        if not self.backup_dir.is_dir():
            return []
        backups = []
        for path in self.backup_dir.iterdir():
            match = _NAME_PATTERN.match(path.name)
            if not match or not path.is_file():
                continue
            try:
                created = datetime.strptime(match.group(1), _STAMP_FORMAT)
                size = path.stat().st_size
            except (ValueError, OSError):
                continue
            backups.append(BackupInfo(path, created, size, match.group(2) == "auto"))
        backups.sort(key=lambda item: (item.created_at, item.path.name), reverse=True)
        return backups

    def prune(self, keep: int) -> list[Path]:
        """Delete automatic backups beyond the newest ``keep``; manual backups are never touched."""
        automatic = [item for item in self.list() if item.automatic]
        removed = []
        for item in automatic[clamp_keep(keep):]:
            item.path.unlink(missing_ok=True)
            removed.append(item.path)
        return removed

    def settings(self) -> dict[str, Any]:
        status = self.schedule.status()
        return {
            "enabled": bool(status.get("enabled", True)),
            "interval_hours": int(status.get("interval_hours", 24)),
            "keep": clamp_keep(read_config(self.config_path).get(KEEP_CONFIG_KEY, DEFAULT_KEEP)),
        }

    def configure(self, enabled: bool, interval_hours: int, keep: int) -> None:
        self.schedule.configure(enabled, interval_hours)
        update_config({KEEP_CONFIG_KEY: clamp_keep(keep)}, self.config_path)

    def run_if_due(self) -> BackupInfo | None:
        """Create an automatic backup and prune old ones when the schedule says it is due."""
        outcome = self.schedule.run_if_due(self._automatic_backup)
        return outcome["result"] if outcome else None

    def _automatic_backup(self) -> BackupInfo:
        backup = self.create(automatic=True)
        self.prune(clamp_keep(read_config(self.config_path).get(KEEP_CONFIG_KEY, DEFAULT_KEEP)))
        return backup

    def restore(self, path: str | Path) -> Path:
        """Replace the database with ``path`` after a manual safety backup; returns that backup."""
        source = Path(path)
        # sqlite3.connect would silently create a missing file and "restore" an empty database.
        if not source.is_file():
            raise FileNotFoundError(source)
        safety = self.create(automatic=False)
        restore_database_backup(source, self.database_path)
        return safety.path
