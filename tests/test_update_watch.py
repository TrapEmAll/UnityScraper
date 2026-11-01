"""Tests for the title update watchlist service."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from unityscraper.domains.library.update_watch import UpdateWatchService


class UpdateWatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "watch.db"
        self.service = UpdateWatchService(self.db_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _execute(self, sql: str, *params: object) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(sql, params)

    def _add_updates(self, titleid: str, *versions: str) -> None:
        for version in versions:
            self._execute(
                "INSERT INTO title_updates(titleid, media_id, version) VALUES (?, 'M1', ?)",
                titleid, version,
            )

    def _add_catalog(self, titleid: str, name: str) -> None:
        self._execute(
            "INSERT INTO xboxunity_title_catalog(titleid, name, source_url, raw_json, fetched_at) "
            "VALUES (?, ?, 'http://xboxunity.net', '{}', '2026-01-01')",
            titleid, name,
        )

    def _inserting_collector(self, *versions: str):
        calls: list[str] = []

        def collect(titleid: str) -> bool:
            calls.append(titleid)
            self._add_updates(titleid, *versions)
            return True

        return collect, calls

    def test_watch_unwatch_normalizes_titleids(self) -> None:
        self.service.set_watched("4d5307e6", True)
        self.service.set_watched("415607D1", True)
        self.assertTrue(self.service.is_watched("4D5307E6"))
        self.assertEqual(self.service.watched_titleids(), {"4D5307E6", "415607D1"})
        self.service.set_watched("4D5307E6", False)
        self.assertFalse(self.service.is_watched("4d5307e6"))
        self.assertEqual(self.service.watched_titleids(), {"415607D1"})

    def test_set_watched_initializes_known_count(self) -> None:
        self._add_updates("4D5307E6", "1", "2")
        self.service.set_watched("4D5307E6", True)
        title = self.service.watched()[0]
        self.assertEqual(title.known_update_count, 2)
        self.assertEqual(title.new_update_count, 0)
        self.assertIsNone(title.last_checked_at)

    def test_check_counts_new_updates_and_accumulates(self) -> None:
        self._add_updates("4D5307E6", "1")
        self.service.set_watched("4D5307E6", True)

        collect, calls = self._inserting_collector("2", "3")
        result = self.service.check("4d5307e6", collect)
        self.assertEqual(calls, ["4D5307E6"])
        self.assertEqual((result.new_updates, result.total_updates, result.error), (2, 3, None))

        collect, _ = self._inserting_collector("4")
        self.service.check("4D5307E6", collect)
        title = self.service.watched()[0]
        self.assertEqual((title.known_update_count, title.new_update_count), (4, 3))
        self.assertEqual(title.last_status, "ok")
        self.assertIsNotNone(title.last_checked_at)

        self.service.acknowledge("4d5307e6")
        self.assertEqual(self.service.watched()[0].new_update_count, 0)

        result = self.service.check("4D5307E6", lambda titleid: True)
        self.assertEqual(result.new_updates, 0)

    def test_new_count_never_negative(self) -> None:
        self._add_updates("4D5307E6", "1", "2")
        self.service.set_watched("4D5307E6", True)

        def shrink(titleid: str) -> bool:
            self._execute("DELETE FROM title_updates WHERE version='2'")
            return True

        result = self.service.check("4D5307E6", shrink)
        self.assertEqual((result.new_updates, result.total_updates), (0, 1))

    def test_acknowledge_all(self) -> None:
        for titleid in ("4D5307E6", "415607D1"):
            self.service.set_watched(titleid, True)
            self.service.check(titleid, self._inserting_collector("1")[0])
        self.service.acknowledge_all()
        self.assertEqual([t.new_update_count for t in self.service.watched()], [0, 0])

    def test_collector_failure_is_recorded_and_returned(self) -> None:
        self.service.set_watched("4D5307E6", True)

        def broken(titleid: str) -> bool:
            raise ConnectionError("Cannot connect to XboxUnity.net")

        result = self.service.check("4D5307E6", broken)
        self.assertEqual(result.error, "Cannot connect to XboxUnity.net")
        self.assertEqual(result.new_updates, 0)
        title = self.service.watched()[0]
        self.assertEqual(title.last_status, "failed")
        self.assertEqual(title.last_error, "Cannot connect to XboxUnity.net")

        self.service.check("4D5307E6", self._inserting_collector("1")[0])
        title = self.service.watched()[0]
        self.assertEqual((title.last_status, title.last_error), ("ok", None))

    def test_check_all_reports_progress(self) -> None:
        self._add_catalog("4D5307E6", "Gears of War")
        self._add_catalog("415607D1", "Alan Wake")
        self.service.set_watched("4D5307E6", True)
        self.service.set_watched("415607D1", True)
        progress: list[tuple[int, int, str]] = []
        collect, calls = self._inserting_collector("1")

        results = self.service.check_all(
            collect, lambda index, total, name: progress.append((index, total, name))
        )
        self.assertEqual(progress, [(1, 2, "Alan Wake"), (2, 2, "Gears of War")])
        self.assertEqual(calls, ["415607D1", "4D5307E6"])
        self.assertEqual([r.new_updates for r in results], [1, 1])

    def test_schedule_disabled_by_default(self) -> None:
        schedule = self.service.schedule()
        state = schedule.status()
        self.assertFalse(state["enabled"])
        self.assertEqual(state["interval_hours"], 24)
        self.assertFalse(schedule.is_due())
        calls: list[str] = []
        self.assertIsNone(self.service.run_if_due(calls.append))
        schedule.configure(True, 1)
        self.assertEqual(schedule.status()["interval_hours"], 6)

    def test_name_fallback_order(self) -> None:
        self._execute("INSERT INTO titleids(titleid, name) VALUES ('AAAA0001', 'Library Name')")
        self._add_catalog("AAAA0001", "Catalog Name")
        self._execute("INSERT INTO titleids(titleid, name) VALUES ('AAAA0002', '')")
        self._add_catalog("AAAA0002", "Catalog Only")
        for titleid in ("AAAA0001", "AAAA0002", "AAAA0003"):
            self.service.set_watched(titleid, True)
        names = {title.titleid: title.name for title in self.service.watched()}
        self.assertEqual(
            names,
            {"AAAA0001": "Library Name", "AAAA0002": "Catalog Only", "AAAA0003": "AAAA0003"},
        )


if __name__ == "__main__":
    unittest.main()
