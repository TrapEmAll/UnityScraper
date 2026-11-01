"""Recent activity and attention items merged from existing audit and status tables."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

from unityscraper.core.paths import DATABASE_PATH

ATTENTION_DAYS = 7
ATTENTION_FAILURE_LIMIT = 20


@dataclass(frozen=True)
class ActivityItem:
    """One feed entry; ``timestamp`` is a fixed-width UTC ISO string, '' when unknown."""

    timestamp: str
    kind: str
    title: str
    detail: str
    status: str


def normalize_timestamp(value: object) -> str:
    """Return ``value`` as a fixed-width UTC ISO string, or '' when it cannot be parsed.

    Naive values (SQLite ``CURRENT_TIMESTAMP``) are UTC. Fixed width keeps string order
    identical to time order, so items from different tables sort correctly as text.
    """
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _label(value: object) -> str:
    return str(value or "").replace("_", " ").capitalize()


def _join(*parts: object) -> str:
    return " · ".join(str(part) for part in parts if part)


def _count(value: object, noun: str) -> str:
    number = int(value or 0)
    return f"{number} {noun}{'s' * (number != 1)}"


Source = tuple[str, str, Callable[[sqlite3.Row], ActivityItem]]


class ActivityFeed:
    """Merge recent backup, catalog, profile, scrape and watch activity, newest first.

    Every source table is optional: older or partial databases simply contribute nothing.
    """

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

    def recent(self, limit: int = 25) -> list[ActivityItem]:
        """Return up to ``limit`` items across all sources, newest first."""
        if limit <= 0:
            return []
        with self._connect() as connection:
            tables = _table_names(connection)
            items = [
                build(row)
                for table, sql, build in _recent_sources(tables)
                if table in tables
                for row in connection.execute(sql, (limit,))
            ]
        items = [item for item in items if item.timestamp]
        items.sort(key=lambda item: item.timestamp, reverse=True)
        return items[:limit]

    def attention(self) -> list[ActivityItem]:
        """Return recent failures and new items that need a look, newest first."""
        cutoff = normalize_timestamp(
            datetime.now(timezone.utc) - timedelta(days=ATTENTION_DAYS)
        )
        with self._connect() as connection:
            tables = _table_names(connection)
            failures = [
                build(row)
                for table, sql, build in _failure_sources()
                if table in tables
                for row in connection.execute(sql, (ATTENTION_FAILURE_LIMIT,))
            ]
            items = [item for item in failures if item.timestamp >= cutoff]
            if "title_updates" in tables:
                row = connection.execute(
                    "SELECT COUNT(*) AS total, MAX(download_date) AS latest "
                    "FROM title_updates WHERE status = 'failed'"
                ).fetchone()
                if row["total"]:
                    items.append(
                        ActivityItem(
                            normalize_timestamp(row["latest"]),
                            "title_updates",
                            f"{_count(row['total'], 'title update')} failed to download",
                            "Retry the failed downloads to complete the archive.",
                            "failed",
                        )
                    )
            if "watch_folders" in tables:
                items.extend(
                    ActivityItem(
                        normalize_timestamp(row["last_scan_at"]),
                        "watch_folder",
                        f"{_count(row['last_new_count'], 'new item')} in "
                        f"{row['label'] or row['path']}",
                        row["path"],
                        "new",
                    )
                    for row in connection.execute(
                        "SELECT path, label, last_scan_at, last_new_count FROM watch_folders "
                        "WHERE enabled = 1 AND last_new_count > 0"
                    )
                )
            if "title_update_watchlist" in tables:
                items.extend(
                    ActivityItem(
                        normalize_timestamp(row["last_checked_at"]),
                        "watchlist",
                        f"{_count(row['new_update_count'], 'new title update')} for "
                        f"{row['name'] or row['titleid']}",
                        row["titleid"],
                        "new",
                    )
                    for row in connection.execute(
                        "SELECT w.titleid, w.last_checked_at, w.new_update_count, "
                        f"{_name_sql(tables)} AS name FROM title_update_watchlist w "
                        "WHERE w.new_update_count > 0"
                    )
                )
        items.sort(key=lambda item: item.timestamp, reverse=True)
        return items


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _name_sql(tables: set[str]) -> str:
    if "titleids" in tables:
        return "(SELECT t.name FROM titleids t WHERE t.titleid = w.titleid)"
    return "NULL"


def _recent_sources(tables: set[str]) -> list[Source]:
    return [
        (
            "backup_operations",
            "SELECT started_at, operation, source, status, error_message "
            "FROM backup_operations ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "backup", _label(row["operation"]),
                _join(row["source"], row["error_message"]), row["status"] or "",
            ),
        ),
        (
            "backup_scans",
            "SELECT started_at, location, status, item_count, error_message "
            "FROM backup_scans ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "backup_scan", "Backup scan",
                _join(
                    row["location"],
                    _count(row["item_count"], "item")
                    if row["status"] == "completed" else row["error_message"],
                ),
                row["status"] or "",
            ),
        ),
        (
            "xboxunity_catalog_sync_runs",
            "SELECT started_at, status, items_upserted, error_message "
            "FROM xboxunity_catalog_sync_runs ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "catalog_sync",
                "XboxUnity catalog sync",
                row["error_message"] or f"{_count(row['items_upserted'], 'title')} updated",
                row["status"] or "",
            ),
        ),
        (
            "profile_save_operations",
            "SELECT started_at, operation_type, target_path, status, error_message "
            "FROM profile_save_operations ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "profile",
                _label(row["operation_type"]),
                _join(row["target_path"], row["error_message"]), row["status"] or "",
            ),
        ),
        (
            "titleids",
            "SELECT titleid, name, last_scraped FROM titleids "
            "WHERE last_scraped IS NOT NULL ORDER BY last_scraped DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["last_scraped"]), "scrape",
                f"Scraped {row['name'] or row['titleid']}", row["titleid"], "completed",
            ),
        ),
        (
            "watch_folders",
            "SELECT path, label, last_scan_at, last_status, last_new_count, last_error "
            "FROM watch_folders WHERE last_scan_at IS NOT NULL "
            "ORDER BY last_scan_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["last_scan_at"]), "watch_folder",
                f"Scanned {row['label'] or row['path']}",
                _join(_count(row["last_new_count"], "new item"), row["last_error"]),
                row["last_status"] or "",
            ),
        ),
        (
            "title_update_watchlist",
            "SELECT w.titleid, w.last_checked_at, w.last_status, w.new_update_count, "
            f"w.last_error, {_name_sql(tables)} AS name FROM title_update_watchlist w "
            "WHERE w.last_checked_at IS NOT NULL ORDER BY w.last_checked_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["last_checked_at"]), "watchlist",
                f"Checked {row['name'] or row['titleid']} for title updates",
                _join(_count(row["new_update_count"], "new update"), row["last_error"]),
                row["last_status"] or "",
            ),
        ),
    ]


def _failure_sources() -> list[Source]:
    return [
        (
            "backup_operations",
            "SELECT started_at, operation, source, error_message FROM backup_operations "
            "WHERE status = 'failed' ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "backup",
                f"{_label(row['operation'])} failed",
                _join(row["source"], row["error_message"]), "failed",
            ),
        ),
        (
            "backup_scans",
            "SELECT started_at, location, error_message FROM backup_scans "
            "WHERE status = 'failed' ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "backup_scan", "Backup scan failed",
                _join(row["location"], row["error_message"]), "failed",
            ),
        ),
        (
            "xboxunity_catalog_sync_runs",
            "SELECT started_at, error_message FROM xboxunity_catalog_sync_runs "
            "WHERE status = 'failed' ORDER BY started_at DESC LIMIT ?",
            lambda row: ActivityItem(
                normalize_timestamp(row["started_at"]), "catalog_sync",
                "XboxUnity catalog sync failed", row["error_message"] or "", "failed",
            ),
        ),
    ]


__all__ = ["ATTENTION_DAYS", "ActivityFeed", "ActivityItem", "normalize_timestamp"]
