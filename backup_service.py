"""Persistence and application services for Xbox backup management."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app_paths import DATABASE_PATH, ensure_app_dirs
from backup_manager import (
    BackupItem,
    FtpBackupClient,
    FtpTarget,
    ScanResult,
    TransferResult,
    export_backup_item,
    import_stfs_zip,
    install_stfs_package,
    scan_local_target,
    verify_backup_item,
)


def ensure_backup_schema(connection: sqlite3.Connection) -> None:
    """Create additive backup-manager tables on an existing connection."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS backup_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('local', 'ftp')),
            location TEXT NOT NULL,
            settings_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(kind, location)
        );

        CREATE TABLE IF NOT EXISTS backup_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER,
            location TEXT NOT NULL,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            total_size INTEGER NOT NULL DEFAULT 0,
            warnings_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_message TEXT,
            FOREIGN KEY (target_id) REFERENCES backup_targets(id)
        );

        CREATE TABLE IF NOT EXISTS backup_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            titleid TEXT,
            name TEXT NOT NULL,
            format TEXT NOT NULL,
            content_type TEXT,
            media_id TEXT,
            path TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            notes_json TEXT,
            FOREIGN KEY (scan_id) REFERENCES backup_scans(id)
        );

        CREATE TABLE IF NOT EXISTS backup_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            source TEXT NOT NULL,
            destination TEXT,
            status TEXT NOT NULL,
            bytes_copied INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT,
            details_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_backup_inventory_titleid
            ON backup_inventory(titleid);
        CREATE INDEX IF NOT EXISTS idx_backup_inventory_scan
            ON backup_inventory(scan_id);
        CREATE INDEX IF NOT EXISTS idx_backup_operations_status
            ON backup_operations(status, started_at);
        """
    )


class BackupRepository:
    """Additive SQLite storage for targets, scans, inventory, and operations."""

    def __init__(self, db_path: str | Path = DATABASE_PATH):
        ensure_app_dirs()
        self.db_path = Path(db_path)
        self.ensure_schema()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            ensure_backup_schema(connection)

    def save_local_target(self, name: str, location: str | Path) -> int:
        now = datetime.now(timezone.utc).isoformat()
        resolved = str(Path(location).expanduser().resolve())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_targets
                    (name, kind, location, settings_json, created_at, updated_at)
                VALUES (?, 'local', ?, '{}', ?, ?)
                ON CONFLICT(kind, location) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (name, resolved, now, now),
            )
            row = connection.execute(
                "SELECT id FROM backup_targets WHERE kind = 'local' AND location = ?",
                (resolved,),
            ).fetchone()
            return int(row["id"])

    def save_ftp_target(self, name: str, target: FtpTarget) -> int:
        """Persist non-secret FTP settings. Passwords are deliberately omitted."""
        now = datetime.now(timezone.utc).isoformat()
        location = f"{target.host}:{target.port}"
        settings = {
            "username": target.username,
            "content_root": target.content_root,
            "games_root": target.games_root,
            "timeout": target.timeout,
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_targets
                    (name, kind, location, settings_json, created_at, updated_at)
                VALUES (?, 'ftp', ?, ?, ?, ?)
                ON CONFLICT(kind, location) DO UPDATE SET
                    name = excluded.name,
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (name, location, json.dumps(settings), now, now),
            )
            row = connection.execute(
                "SELECT id FROM backup_targets WHERE kind = 'ftp' AND location = ?",
                (location,),
            ).fetchone()
            return int(row["id"])

    def list_targets(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM backup_targets ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_scan(self, location: str, target_id: Optional[int] = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO backup_scans
                    (target_id, location, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (target_id, location, datetime.now(timezone.utc).isoformat()),
            )
            return int(cursor.lastrowid)

    def finish_scan(self, scan_id: int, result: ScanResult) -> None:
        with self.connect() as connection:
            for item in result.items:
                connection.execute(
                    """
                    INSERT INTO backup_inventory (
                        scan_id, titleid, name, format, content_type, media_id,
                        path, size, status, notes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        item.title_id,
                        item.name,
                        item.format,
                        item.content_type,
                        item.media_id,
                        str(item.path),
                        item.size,
                        item.status,
                        json.dumps(item.notes),
                    ),
                )
            connection.execute(
                """
                UPDATE backup_scans
                SET status = 'completed', item_count = ?, total_size = ?,
                    warnings_json = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    len(result.items),
                    result.total_size,
                    json.dumps(result.warnings),
                    datetime.now(timezone.utc).isoformat(),
                    scan_id,
                ),
            )

    def fail_scan(self, scan_id: int, error: Exception) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE backup_scans
                SET status = 'failed', error_message = ?, finished_at = ?
                WHERE id = ?
                """,
                (str(error), datetime.now(timezone.utc).isoformat(), scan_id),
            )

    def record_operation(
        self,
        operation: str,
        source: str,
        destination: str = "",
        result: Optional[TransferResult] = None,
        error: Optional[Exception] = None,
        details: Optional[dict] = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        status = "failed" if error else (result.status if result else "completed")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO backup_operations (
                    operation, source, destination, status, bytes_copied,
                    sha256, details_json, started_at, finished_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation,
                    source,
                    destination or (result.destination if result else ""),
                    status,
                    result.bytes_copied if result else 0,
                    result.sha256 if result else "",
                    json.dumps(details or {}),
                    now,
                    now,
                    str(error) if error else None,
                ),
            )
            return int(cursor.lastrowid)


class BackupService:
    """Coordinates backup operations with metadata lookup and audit records."""

    def __init__(self, db_path: str | Path = DATABASE_PATH):
        self.repository = BackupRepository(db_path)

    def title_name(self, title_id: str) -> Optional[str]:
        if not title_id:
            return None
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT name FROM titleids WHERE titleid = ?",
                (title_id.upper(),),
            ).fetchone()
        return row["name"] if row and row["name"] else None

    def scan(self, root: str | Path, target_name: str = "Local target") -> ScanResult:
        target_id = self.repository.save_local_target(target_name, root)
        scan_id = self.repository.begin_scan(str(Path(root).resolve()), target_id)
        try:
            result = scan_local_target(root, self.title_name)
            self.repository.finish_scan(scan_id, result)
            return result
        except Exception as exc:
            self.repository.fail_scan(scan_id, exc)
            raise

    def install_package(
        self, source: str | Path, target: str | Path, conflict: str = "skip"
    ) -> TransferResult:
        try:
            result = install_stfs_package(source, target, conflict)
            self.repository.record_operation("install_stfs", str(source), result=result)
            return result
        except Exception as exc:
            self.repository.record_operation(
                "install_stfs", str(source), str(target), error=exc
            )
            raise

    def import_archive(
        self, source: str | Path, target: str | Path, conflict: str = "skip"
    ) -> list[TransferResult]:
        try:
            results = import_stfs_zip(source, target, conflict)
            self.repository.record_operation(
                "import_stfs_zip",
                str(source),
                str(target),
                details={"results": [asdict(result) for result in results]},
            )
            return results
        except Exception as exc:
            self.repository.record_operation(
                "import_stfs_zip", str(source), str(target), error=exc
            )
            raise

    def export(
        self, item: BackupItem, destination: str | Path, conflict: str = "skip"
    ) -> Path:
        try:
            result = export_backup_item(item, destination, conflict)
            self.repository.record_operation(
                "export_backup",
                str(item.path),
                str(result),
                details={"title_id": item.title_id},
            )
            return result
        except Exception as exc:
            self.repository.record_operation(
                "export_backup", str(item.path), str(destination), error=exc
            )
            raise

    def verify(self, item: BackupItem) -> list[str]:
        issues = verify_backup_item(item)
        self.repository.record_operation(
            "verify_backup",
            str(item.path),
            details={"issues": issues},
        )
        return issues

    def upload_ftp(
        self, source: str | Path, target: FtpTarget
    ) -> TransferResult:
        self.repository.save_ftp_target(target.host, target)
        try:
            result = FtpBackupClient(target).upload_stfs(source)
            self.repository.record_operation("ftp_upload", str(source), result=result)
            return result
        except Exception as exc:
            self.repository.record_operation(
                "ftp_upload", str(source), f"{target.host}:{target.port}", error=exc
            )
            raise
