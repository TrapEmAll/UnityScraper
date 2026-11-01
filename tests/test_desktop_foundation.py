"""Tests for the shared desktop foundation: theme, config, scheduling, notifications."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import DatabaseManager
from ui_theme import ACCENTS, PALETTE, THEMES, mix, set_theme
from unityscraper.core.config import read_config, update_config
from unityscraper.core.notifications import HISTORY_LIMIT, NotificationService
from unityscraper.core.scheduling import ScheduledTask


class TestTheme(unittest.TestCase):
    def tearDown(self):
        set_theme()

    def test_mix_blends_channels(self):
        self.assertEqual(mix("#FFFFFF", "#000000", 1.0), "#FFFFFF")
        self.assertEqual(mix("#FFFFFF", "#000000", 0.0), "#000000")
        self.assertEqual(mix("#FF0000", "#0000FF", 0.5), "#800080")

    def test_light_theme_uses_light_accent_shade(self):
        set_theme("light", "blue")
        self.assertEqual(PALETTE.window, THEMES["light"]["window"])
        self.assertEqual(PALETTE.accent, ACCENTS["blue"][1])

    def test_high_contrast_ignores_accent_choice(self):
        set_theme("high_contrast", "pink")
        self.assertEqual(PALETTE.accent, "#FFFF00")
        self.assertEqual(PALETTE.selection, "#FFFF00")

    def test_unknown_names_fall_back_to_defaults(self):
        set_theme("neon", "chartreuse")
        self.assertEqual(PALETTE.window, THEMES["dark"]["window"])
        self.assertEqual(PALETTE.accent, ACCENTS["green"][0])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.path = self.temp_dir / "nested" / "config.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_missing_or_corrupt_config_reads_empty(self):
        self.assertEqual(read_config(self.path), {})
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(read_config(self.path), {})
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(read_config(self.path), {})

    def test_update_merges_without_dropping_keys(self):
        update_config({"theme": "dark", "workers": 4}, self.path)
        update_config({"theme": "light"}, self.path)
        self.assertEqual(read_config(self.path), {"theme": "light", "workers": 4})
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())


class TestScheduledTask(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "library.db"
        DatabaseManager(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_default_enabled_task_runs_then_waits_for_interval(self):
        task = ScheduledTask(self.db_path, "demo", default_interval_hours=12, default_enabled=True)
        self.assertEqual(task.run_if_due(lambda: "done")["result"], "done")
        self.assertIsNone(task.run_if_due(lambda: "again"))
        later = datetime.now(timezone.utc) + timedelta(hours=13)
        self.assertTrue(task.is_due(later))

    def test_existing_state_survives_new_defaults(self):
        ScheduledTask(self.db_path, "demo", default_enabled=False).configure(True, 48)
        task = ScheduledTask(self.db_path, "demo", default_interval_hours=6, default_enabled=False)
        self.assertEqual(task.status()["interval_hours"], 48)
        self.assertTrue(task.status()["enabled"])

    def test_interval_is_clamped_to_minimum(self):
        task = ScheduledTask(self.db_path, "demo", min_interval_hours=6)
        task.configure(True, 1)
        self.assertEqual(task.status()["interval_hours"], 6)

    def test_failure_is_recorded_and_reraised(self):
        task = ScheduledTask(self.db_path, "demo", default_enabled=True)

        def broken():
            raise RuntimeError("offline")

        with self.assertRaises(RuntimeError):
            task.run_if_due(broken)
        status = task.status()
        self.assertEqual(status["last_status"], "failed")
        self.assertEqual(status["last_error"], "offline")
        self.assertTrue(task.is_due())

    def test_tasks_are_independent(self):
        first = ScheduledTask(self.db_path, "first", default_enabled=True)
        second = ScheduledTask(self.db_path, "second", default_enabled=True)
        first.run(lambda: None)
        self.assertFalse(first.is_due())
        self.assertTrue(second.is_due())


class TestNotifications(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.service = NotificationService(self.temp_dir / "library.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_unread_count_and_mark_read(self):
        self.service.add("info", "First")
        self.service.add("error", "Second", "details", "Scan")
        self.assertEqual(self.service.unread_count(), 2)
        newest = self.service.recent(1)[0]
        self.assertEqual((newest.title, newest.message, newest.source), ("Second", "details", "Scan"))
        self.service.mark_all_read()
        self.assertEqual(self.service.unread_count(), 0)
        self.assertTrue(all(item.read for item in self.service.recent()))

    def test_rejects_unknown_level(self):
        with self.assertRaises(ValueError):
            self.service.add("critical", "Nope")

    def test_history_is_bounded_to_newest_entries(self):
        for index in range(HISTORY_LIMIT + 5):
            self.service.add("info", f"Item {index}")
        items = self.service.recent(HISTORY_LIMIT + 10)
        self.assertEqual(len(items), HISTORY_LIMIT)
        self.assertEqual(items[0].title, f"Item {HISTORY_LIMIT + 4}")
        self.assertEqual(items[-1].title, "Item 5")


if __name__ == "__main__":
    unittest.main()
