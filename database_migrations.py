"""Versioned, additive database migrations and backup helpers."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_database_backup(db_path: str | Path, destination: str | Path | None = None) -> Path:
    """Create a consistent SQLite backup without modifying the source database."""
    source_path = Path(db_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(destination) if destination else source_path.with_suffix(f".{stamp}.bak")
    if source_path.resolve() == target.resolve():
        raise ValueError("Backup destination must differ from the active database")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(target) as output:
        source.backup(output)
    return target


def restore_database_backup(backup_path: str | Path, db_path: str | Path) -> Path:
    """Restore a user-selected backup after validating that it is SQLite."""
    source = Path(backup_path)
    target = Path(db_path)
    if source.resolve() == target.resolve():
        raise ValueError("Restore source must differ from the active database")
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA schema_version").fetchone()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".restore")
    shutil.copy2(source, temporary)
    temporary.replace(target)
    return target


def ensure_application_schema(connection: sqlite3.Connection) -> int:
    """Apply every additive UnityScraper schema migration."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM app_schema_migrations").fetchall()
    }
    migrations = (
        (1, "collection intelligence", _migration_collection),
        (2, "preservation records", _migration_preservation),
        (3, "console synchronization", _migration_console_sync),
        (4, "user overrides and recovery", _migration_reliability),
        (5, "XboxUnity title catalog", _migration_xboxunity_catalog),
    )
    for version, name, migration in migrations:
        if version in applied:
            continue
        migration(connection)
        connection.execute(
            "INSERT INTO app_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, _now()),
        )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return SCHEMA_VERSION


def _migration_collection(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS collection_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,
            source_location TEXT NOT NULL,
            label TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            item_count INTEGER NOT NULL DEFAULT 0,
            total_size INTEGER NOT NULL DEFAULT 0,
            health_score INTEGER,
            status TEXT NOT NULL DEFAULT 'running',
            warnings_json TEXT
        );
        CREATE TABLE IF NOT EXISTS collection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            titleid TEXT,
            media_id TEXT,
            name TEXT NOT NULL,
            format TEXT NOT NULL,
            content_type TEXT,
            path TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            disc_number INTEGER,
            disc_count INTEGER,
            status TEXT NOT NULL,
            compatibility TEXT,
            notes_json TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES collection_snapshots(id)
        );
        CREATE INDEX IF NOT EXISTS idx_collection_items_titleid
            ON collection_items(titleid, media_id);
        CREATE INDEX IF NOT EXISTS idx_collection_items_snapshot
            ON collection_items(snapshot_id);
        """
    )


def _migration_preservation(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_file_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            crc32 TEXT,
            md5 TEXT,
            sha1 TEXT,
            sha256 TEXT,
            calculated_at TEXT NOT NULL,
            UNIQUE(path, size, modified_ns)
        );
        CREATE INDEX IF NOT EXISTS idx_local_hash_sha256 ON local_file_hashes(sha256);
        CREATE INDEX IF NOT EXISTS idx_local_hash_sha1 ON local_file_hashes(sha1);
        CREATE TABLE IF NOT EXISTS preservation_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            matched_at TEXT NOT NULL,
            UNIQUE(file_hash_id, entity_id, identifier_type),
            FOREIGN KEY(file_hash_id) REFERENCES local_file_hashes(id),
            FOREIGN KEY(entity_id) REFERENCES knowledge_entities(id)
        );
        CREATE TABLE IF NOT EXISTS repair_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            summary_json TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES collection_snapshots(id)
        );
        CREATE TABLE IF NOT EXISTS repair_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target TEXT NOT NULL,
            reason TEXT NOT NULL,
            destructive INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'proposed',
            details_json TEXT,
            FOREIGN KEY(plan_id) REFERENCES repair_plans(id)
        );
        """
    )


def _migration_console_sync(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS console_inventory_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER,
            label TEXT,
            root TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running',
            error_message TEXT,
            FOREIGN KEY(target_id) REFERENCES backup_targets(id)
        );
        CREATE TABLE IF NOT EXISTS console_inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            remote_path TEXT NOT NULL,
            size INTEGER,
            modified_at TEXT,
            is_directory INTEGER NOT NULL DEFAULT 0,
            titleid TEXT,
            media_id TEXT,
            UNIQUE(snapshot_id, remote_path),
            FOREIGN KEY(snapshot_id) REFERENCES console_inventory_snapshots(id)
        );
        CREATE TABLE IF NOT EXISTS console_transfer_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER,
            direction TEXT NOT NULL CHECK(direction IN ('upload', 'download')),
            local_path TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            transferred_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 100,
            bandwidth_limit INTEGER NOT NULL DEFAULT 0,
            expected_sha256 TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(target_id) REFERENCES backup_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_console_jobs_status
            ON console_transfer_jobs(status, priority, created_at);
        """
    )


def _migration_reliability(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            property TEXT NOT NULL,
            value TEXT NOT NULL,
            notes TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(entity_type, identifier_type, identifier_value, property)
        );
        CREATE TABLE IF NOT EXISTS recovery_state (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def _migration_xboxunity_catalog(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS xboxunity_title_catalog (
            titleid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hb_titleid TEXT,
            title_type TEXT,
            link_enabled INTEGER NOT NULL DEFAULT 0,
            covers_count INTEGER NOT NULL DEFAULT 0,
            updates_count INTEGER NOT NULL DEFAULT 0,
            media_id_count INTEGER NOT NULL DEFAULT 0,
            user_count INTEGER NOT NULL DEFAULT 0,
            newest_content TEXT,
            source_url TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_xboxunity_catalog_name
            ON xboxunity_title_catalog(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_xboxunity_catalog_type
            ON xboxunity_title_catalog(title_type);

        CREATE TABLE IF NOT EXISTS xboxunity_catalog_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            pages_expected INTEGER NOT NULL DEFAULT 0,
            pages_fetched INTEGER NOT NULL DEFAULT 0,
            items_upserted INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        """
    )
