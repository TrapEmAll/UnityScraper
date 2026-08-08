"""Backup domain schema migrations."""

from __future__ import annotations

import sqlite3


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


__all__ = ["ensure_backup_schema"]
