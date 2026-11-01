"""Tests for the home activity feed: merge order, missing tables, limits and attention."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import DatabaseManager
from unityscraper.domains.library.activity import ActivityFeed, normalize_timestamp


def iso_ago(**delta: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def sqlite_ago(**delta: float) -> str:
    """CURRENT_TIMESTAMP style: naive UTC without fractional seconds."""
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


class TestNormalizeTimestamp(unittest.TestCase):
    def test_formats_normalize_to_fixed_width_utc(self):
        expected = "2026-01-01T10:00:00.000000+00:00"
        self.assertEqual(normalize_timestamp("2026-01-01 10:00:00"), expected)
        self.assertEqual(normalize_timestamp("2026-01-01T12:00:00+02:00"), expected)
        self.assertEqual(normalize_timestamp("2026-01-01T10:00:00Z"), expected)
        self.assertEqual(normalize_timestamp(None), "")
        self.assertEqual(normalize_timestamp("not a date"), "")


class TestActivityFeed(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.path = self.temp_dir / "activity.db"
        DatabaseManager(str(self.path))
        self.feed = ActivityFeed(self.path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def execute(self, sql: str, *params: object) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(sql, params)
            connection.commit()

    def add_backup_operation(self, started_at: str, status: str = "completed") -> None:
        self.execute(
            "INSERT INTO backup_operations(operation, source, status, started_at, error_message) "
            "VALUES ('install_stfs', 'C:/games/pkg', ?, ?, ?)",
            status, started_at, "disk full" if status == "failed" else None,
        )

    def add_catalog_run(self, started_at: str, status: str = "completed") -> None:
        self.execute(
            "INSERT INTO xboxunity_catalog_sync_runs(started_at, status, items_upserted) "
            "VALUES (?, ?, 12)",
            started_at, status,
        )

    def add_watch_folder(self, path: str, new_count: int, enabled: int = 1) -> None:
        self.execute(
            "INSERT INTO watch_folders(path, enabled, created_at, last_scan_at, last_status, "
            "last_new_count) VALUES (?, ?, ?, ?, 'completed', ?)",
            path, enabled, iso_ago(days=30), iso_ago(minutes=10), new_count,
        )

    def add_watchlist(self, titleid: str, new_count: int, checked_at: str) -> None:
        self.execute(
            "INSERT INTO title_update_watchlist(titleid, added_at, last_checked_at, "
            "last_status, new_update_count) VALUES (?, ?, ?, 'completed', ?)",
            titleid, iso_ago(days=30), checked_at, new_count,
        )

    def test_recent_merges_sources_newest_first_across_timestamp_formats(self):
        self.execute(
            "INSERT INTO titleids(titleid, name, last_scraped) VALUES ('4D5307E6', 'Halo 3', ?)",
            sqlite_ago(hours=1),
        )
        self.add_backup_operation(iso_ago(minutes=30))
        # Two hours ago written with a +02:00 offset: its wall-clock text reads as "now".
        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        self.add_catalog_run(two_hours_ago.astimezone(timezone(timedelta(hours=2))).isoformat())
        self.add_watch_folder("D:/incoming", new_count=2)
        self.add_watchlist("4D5307E6", 0, iso_ago(hours=3))

        items = self.feed.recent()

        self.assertEqual(
            [item.kind for item in items],
            ["watch_folder", "backup", "scrape", "catalog_sync", "watchlist"],
        )
        self.assertEqual(items[2].title, "Scraped Halo 3")
        self.assertIn("Halo 3", items[4].title)
        self.assertEqual([item.timestamp for item in items],
                         sorted((item.timestamp for item in items), reverse=True))

    def test_missing_tables_are_skipped(self):
        for table in ("backup_operations", "title_updates", "titleids", "watch_folders"):
            self.execute(f"DROP TABLE {table}")
        self.add_catalog_run(iso_ago(hours=1), status="failed")

        self.assertEqual([item.kind for item in self.feed.recent()], ["catalog_sync"])
        self.assertEqual([item.kind for item in self.feed.attention()], ["catalog_sync"])

    def test_limit_is_respected(self):
        for minutes in range(5):
            self.add_backup_operation(iso_ago(minutes=minutes * 2))
            self.add_catalog_run(iso_ago(minutes=minutes * 2 + 1))

        items = self.feed.recent(limit=3)

        self.assertEqual(
            [item.kind for item in items], ["backup", "catalog_sync", "backup"]
        )
        self.assertEqual(self.feed.recent(limit=0), [])

    def test_attention_picks_only_recent_failures_and_new_items(self):
        self.add_backup_operation(iso_ago(days=1), status="failed")
        self.add_backup_operation(iso_ago(days=10), status="failed")
        self.add_backup_operation(iso_ago(hours=1))
        self.execute(
            "INSERT INTO backup_scans(location, status, started_at, error_message) "
            "VALUES ('F:/', 'failed', ?, 'unreadable')",
            iso_ago(days=2),
        )
        self.add_catalog_run(iso_ago(minutes=5), status="failed")
        self.add_catalog_run(iso_ago(minutes=1))
        for media_id, status in (("A", "failed"), ("B", "failed"), ("C", "downloaded")):
            self.execute(
                "INSERT INTO title_updates(titleid, media_id, version, status) "
                "VALUES ('4D5307E6', ?, '1', ?)",
                media_id, status,
            )
        self.add_watch_folder("D:/new", new_count=3)
        self.add_watch_folder("D:/quiet", new_count=0)
        self.add_watch_folder("D:/disabled", new_count=5, enabled=0)
        self.add_watchlist("4D5307E6", 2, iso_ago(hours=4))
        self.add_watchlist("41560817", 0, iso_ago(hours=4))

        items = self.feed.attention()

        self.assertEqual(
            [item.kind for item in items],
            ["catalog_sync", "watch_folder", "watchlist", "backup", "backup_scan",
             "title_updates"],
        )
        self.assertEqual(items[1].detail, "D:/new")
        self.assertEqual(items[2].detail, "4D5307E6")
        self.assertTrue(items[-1].title.startswith("2 title updates"))
        self.assertEqual({item.status for item in items}, {"failed", "new"})


if __name__ == "__main__":
    unittest.main()
