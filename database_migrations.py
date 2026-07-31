"""Versioned, additive database migrations and backup helpers."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 8


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
        (6, "profile and save management", _migration_profiles_and_saves),
        (7, "profile intelligence and knowledge controls", _migration_roadmap),
        (8, "community roadmap workspaces", _migration_community_roadmap),
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


def _migration_profiles_and_saves(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS profile_scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_root TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            profile_count INTEGER NOT NULL DEFAULT 0,
            save_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            warnings_json TEXT,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS xbox_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            gamertag TEXT,
            source_path TEXT NOT NULL,
            package_path TEXT,
            package_sha256 TEXT,
            console_id TEXT,
            device_id TEXT,
            profile_kind TEXT NOT NULL DEFAULT 'unknown',
            package_status TEXT NOT NULL DEFAULT 'unverified',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(profile_id, source_path)
        );
        CREATE INDEX IF NOT EXISTS idx_xbox_profiles_profile_id
            ON xbox_profiles(profile_id);

        CREATE TABLE IF NOT EXISTS profile_saves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            titleid TEXT NOT NULL,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL UNIQUE,
            package_magic TEXT,
            content_type INTEGER,
            save_game_id TEXT,
            embedded_profile_id TEXT,
            console_id TEXT,
            device_id TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            modified_at TEXT,
            sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'unverified',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            metadata_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_profile_saves_owner
            ON profile_saves(profile_id, titleid);
        CREATE INDEX IF NOT EXISTS idx_profile_saves_sha256
            ON profile_saves(sha256);

        CREATE TABLE IF NOT EXISTS save_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT,
            label TEXT,
            source_root TEXT NOT NULL,
            snapshot_path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_size INTEGER NOT NULL DEFAULT 0,
            manifest_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'creating',
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS save_snapshot_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_at TEXT,
            item_kind TEXT NOT NULL,
            titleid TEXT,
            restore_status TEXT,
            UNIQUE(snapshot_id, relative_path),
            FOREIGN KEY(snapshot_id) REFERENCES save_snapshots(id)
        );
        CREATE INDEX IF NOT EXISTS idx_save_snapshot_files_snapshot
            ON save_snapshot_files(snapshot_id);

        CREATE TABLE IF NOT EXISTS profile_save_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type TEXT NOT NULL,
            target_path TEXT,
            snapshot_id INTEGER,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            details_json TEXT,
            error_message TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES save_snapshots(id)
        );
        """
    )


def _migration_roadmap(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS profile_gpd_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT,
            titleid TEXT,
            source_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            version INTEGER NOT NULL,
            entry_count INTEGER NOT NULL,
            achievement_count INTEGER NOT NULL DEFAULT 0,
            unlocked_count INTEGER NOT NULL DEFAULT 0,
            gamerscore_earned INTEGER NOT NULL DEFAULT 0,
            gamerscore_possible INTEGER NOT NULL DEFAULT 0,
            parsed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'parsed',
            warnings_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_profile_gpd_owner
            ON profile_gpd_files(profile_id, titleid);

        CREATE TABLE IF NOT EXISTS profile_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gpd_file_id INTEGER NOT NULL,
            achievement_id INTEGER NOT NULL,
            title TEXT,
            locked_description TEXT,
            unlocked_description TEXT,
            gamerscore INTEGER NOT NULL DEFAULT 0,
            unlock_state TEXT NOT NULL,
            unlocked_at TEXT,
            image_id INTEGER,
            entry_id INTEGER,
            UNIQUE(gpd_file_id, achievement_id),
            FOREIGN KEY(gpd_file_id) REFERENCES profile_gpd_files(id)
        );
        CREATE INDEX IF NOT EXISTS idx_profile_achievements_state
            ON profile_achievements(gpd_file_id, unlock_state);

        CREATE TABLE IF NOT EXISTS profile_comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            left_profile_id TEXT NOT NULL,
            right_profile_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS xenia_migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_profile_id TEXT NOT NULL,
            target_profile_id TEXT NOT NULL,
            destination_root TEXT NOT NULL,
            snapshot_id INTEGER,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            copied_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            conflict_count INTEGER NOT NULL DEFAULT 0,
            plan_json TEXT NOT NULL,
            error_message TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES save_snapshots(id)
        );

        CREATE TABLE IF NOT EXISTS knowledge_source_priorities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            updated_at TEXT NOT NULL,
            UNIQUE(property, source_id),
            FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
        );

        CREATE TABLE IF NOT EXISTS knowledge_conflict_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conflict_id INTEGER NOT NULL,
            resolution TEXT NOT NULL,
            preferred_value TEXT,
            preferred_source_id INTEGER,
            notes TEXT,
            resolved_at TEXT NOT NULL,
            FOREIGN KEY(conflict_id) REFERENCES knowledge_conflicts(id),
            FOREIGN KEY(preferred_source_id) REFERENCES knowledge_sources(id)
        );

        CREATE TABLE IF NOT EXISTS scheduled_sync_state (
            task_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            interval_hours INTEGER NOT NULL DEFAULT 168,
            last_started_at TEXT,
            last_completed_at TEXT,
            last_status TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    transfer_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(console_transfer_jobs)")
    }
    if "verify_remote_hash" not in transfer_columns:
        connection.execute(
            """
            ALTER TABLE console_transfer_jobs
            ADD COLUMN verify_remote_hash INTEGER NOT NULL DEFAULT 0
            """
        )


def _migration_community_roadmap(connection: sqlite3.Connection) -> None:
    """Add durable records for the community-facing roadmap workspaces."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS structured_knowledge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            record_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.75,
            extracted_at TEXT NOT NULL,
            UNIQUE(document_id, record_type, normalized_name),
            FOREIGN KEY(document_id) REFERENCES source_documents(id),
            FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
        );
        CREATE INDEX IF NOT EXISTS idx_structured_knowledge_lookup
            ON structured_knowledge_records(record_type, normalized_name);

        CREATE TABLE IF NOT EXISTS console_sync_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_slug TEXT NOT NULL,
            local_root TEXT NOT NULL,
            remote_root TEXT NOT NULL,
            snapshot_id INTEGER,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            summary_json TEXT NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES console_inventory_snapshots(id)
        );
        CREATE TABLE IF NOT EXISTS console_sync_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            local_path TEXT,
            remote_path TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'preview',
            FOREIGN KEY(plan_id) REFERENCES console_sync_plans(id)
        );

        CREATE TABLE IF NOT EXISTS profile_migration_previews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            target_profile_id TEXT,
            target_device_id TEXT,
            target_console_id TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            warnings_json TEXT NOT NULL,
            changes_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profile_gpd_titles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gpd_file_id INTEGER NOT NULL,
            entry_id INTEGER NOT NULL,
            titleid TEXT NOT NULL,
            title TEXT,
            achievements_earned INTEGER NOT NULL DEFAULT 0,
            achievements_possible INTEGER NOT NULL DEFAULT 0,
            gamerscore_earned INTEGER NOT NULL DEFAULT 0,
            gamerscore_possible INTEGER NOT NULL DEFAULT 0,
            last_played_at TEXT,
            UNIQUE(gpd_file_id, entry_id),
            FOREIGN KEY(gpd_file_id) REFERENCES profile_gpd_files(id)
        );
        CREATE TABLE IF NOT EXISTS profile_gpd_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gpd_file_id INTEGER NOT NULL,
            entry_id INTEGER NOT NULL,
            image_format TEXT NOT NULL,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            UNIQUE(gpd_file_id, entry_id),
            FOREIGN KEY(gpd_file_id) REFERENCES profile_gpd_files(id)
        );
        CREATE TABLE IF NOT EXISTS save_comparison_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            left_path TEXT NOT NULL,
            right_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            identical INTEGER NOT NULL,
            summary_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artwork_preferences (
            titleid TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            artwork_type TEXT NOT NULL DEFAULT 'cover',
            region TEXT,
            language TEXT,
            width INTEGER,
            height INTEGER,
            sha256 TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artwork_export_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            destination TEXT NOT NULL,
            preset TEXT NOT NULL,
            created_at TEXT NOT NULL,
            exported_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            manifest_path TEXT,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS disc_set_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER,
            titleid TEXT NOT NULL,
            media_id TEXT,
            expected_count INTEGER NOT NULL,
            present_json TEXT NOT NULL,
            missing_json TEXT NOT NULL,
            status TEXT NOT NULL,
            audited_at TEXT NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES collection_snapshots(id)
        );
        CREATE TABLE IF NOT EXISTS dedup_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root TEXT NOT NULL,
            created_at TEXT NOT NULL,
            duplicate_groups INTEGER NOT NULL DEFAULT 0,
            reclaimable_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'preview'
        );
        CREATE TABLE IF NOT EXISTS dedup_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            keeper_path TEXT NOT NULL,
            duplicate_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            action TEXT NOT NULL DEFAULT 'review',
            status TEXT NOT NULL DEFAULT 'preview',
            FOREIGN KEY(plan_id) REFERENCES dedup_plans(id)
        );

        CREATE TABLE IF NOT EXISTS storage_source_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            filesystem TEXT,
            access_mode TEXT NOT NULL DEFAULT 'read-only',
            detected_at TEXT NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS original_xbox_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titleid TEXT,
            title_name TEXT NOT NULL,
            xbe_path TEXT NOT NULL UNIQUE,
            region_flags TEXT,
            version TEXT,
            compatibility TEXT,
            metadata_json TEXT NOT NULL,
            scanned_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plugin_states (
            plugin_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            trusted_sha256 TEXT,
            permissions_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recovery_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            recoverable INTEGER NOT NULL DEFAULT 1,
            details_json TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS dashboard_compatibility_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_slug TEXT NOT NULL,
            host_label TEXT,
            tested_at TEXT NOT NULL,
            feature TEXT NOT NULL,
            supported INTEGER NOT NULL,
            details TEXT,
            UNIQUE(dashboard_slug, host_label, feature)
        );
        CREATE TABLE IF NOT EXISTS accessibility_preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
