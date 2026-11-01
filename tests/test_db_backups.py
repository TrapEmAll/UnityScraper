"""Tests for automatic database backups: naming, retention, scheduling and restore."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unityscraper.core.config import update_config
from unityscraper.core.db_backups import AutoBackupService


def _write_value(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT)")
        connection.execute("DELETE FROM marker")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.commit()


def _read_value(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM marker").fetchone()[0]


class TestAutoBackupService(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db_path = self.temp / "unityscraper.db"
        self.backup_dir = self.temp / "backups"
        self.config_path = self.temp / "config.json"
        self.service = AutoBackupService(self.db_path, self.backup_dir, self.config_path)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _fake_backup(self, stamp: str, kind: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.backup_dir / f"unityscraper-{stamp}-{kind}.db"
        path.write_bytes(b"x")
        return path

    def test_create_names_and_lists_newest_first_ignoring_foreign_files(self):
        manual = self.service.create(automatic=False)
        automatic = self.service.create(automatic=True)
        second_manual = self.service.create(automatic=False)
        for name in (
            "notes.db",
            "unityscraper-2024-auto.db",
            "unityscraper-20240101-000000-auto.db.partial",
            "unityscraper-20240101-000000-weekly.db",
        ):
            (self.backup_dir / name).write_bytes(b"x")

        self.assertRegex(manual.path.name, r"^unityscraper-\d{8}-\d{6}-manual\.db$")
        self.assertRegex(automatic.path.name, r"^unityscraper-\d{8}-\d{6}-auto\.db$")
        self.assertNotEqual(manual.path, second_manual.path)  # same-second collision avoided
        listed = self.service.list()
        self.assertEqual(
            {item.path for item in listed},
            {manual.path, automatic.path, second_manual.path},
        )
        self.assertEqual(listed[0].path, second_manual.path)
        self.assertEqual([item.created_at for item in listed],
                         sorted((item.created_at for item in listed), reverse=True))
        self.assertTrue(next(item for item in listed if item.path == automatic.path).automatic)
        self.assertGreater(manual.size, 0)

    def test_prune_keeps_newest_automatic_and_never_deletes_manual(self):
        autos = [self._fake_backup(f"20240101-00000{index}", "auto") for index in range(5)]
        manuals = [self._fake_backup(f"20230101-00000{index}", "manual") for index in range(2)]

        removed = self.service.prune(2)

        self.assertEqual(set(removed), set(autos[:3]))
        self.assertTrue(all(path.exists() for path in autos[3:] + manuals))
        self.assertFalse(any(path.exists() for path in autos[:3]))
        self.service.prune(0)  # clamps to keeping one
        self.assertTrue(autos[4].exists())
        self.assertFalse(autos[3].exists())
        self.assertTrue(all(path.exists() for path in manuals))

    def test_run_if_due_respects_enabled_and_interval(self):
        self.service.configure(False, 24, 1)
        self.assertIsNone(self.service.run_if_due())
        self.assertEqual(self.service.list(), [])

        self.service.configure(True, 24, 1)
        first = self.service.run_if_due()
        self.assertIsNotNone(first)
        self.assertTrue(first.automatic)
        self.assertIsNone(self.service.run_if_due())  # completed just now, not due

        stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE scheduled_sync_state SET last_completed_at=? WHERE task_name=?",
                (stale, "database-backup"),
            )
            connection.commit()
        second = self.service.run_if_due()
        self.assertIsNotNone(second)
        self.assertEqual([item.path for item in self.service.list()], [second.path])  # keep=1

    def test_restore_creates_safety_backup_and_replaces_content(self):
        _write_value(self.db_path, "current")
        source = self.temp / "other.db"
        _write_value(source, "restored")

        safety = self.service.restore(source)

        self.assertEqual(_read_value(self.db_path), "restored")
        self.assertEqual(_read_value(safety), "current")
        listed = self.service.list()
        self.assertEqual([item.path for item in listed], [safety])
        self.assertFalse(listed[0].automatic)

    def test_restore_rejects_missing_and_non_sqlite_files(self):
        _write_value(self.db_path, "current")
        with self.assertRaises(FileNotFoundError):
            self.service.restore(self.temp / "missing.db")
        junk = self.temp / "junk.db"
        junk.write_bytes(b"not a database at all, just some bytes" * 10)
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.restore(junk)
        self.assertEqual(_read_value(self.db_path), "current")

    def test_settings_defaults_and_clamping(self):
        self.assertEqual(
            self.service.settings(), {"enabled": True, "interval_hours": 24, "keep": 7}
        )
        self.service.configure(True, 0, 500)
        self.assertEqual(self.service.settings()["keep"], 100)
        self.assertEqual(self.service.settings()["interval_hours"], 1)
        self.service.configure(False, 48, -3)
        self.assertEqual(
            self.service.settings(), {"enabled": False, "interval_hours": 48, "keep": 1}
        )
        update_config({"database_backup_keep": "lots"}, self.config_path)
        self.assertEqual(self.service.settings()["keep"], 7)


if __name__ == "__main__":
    unittest.main()
