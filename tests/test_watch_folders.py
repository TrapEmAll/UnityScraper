"""Tests for watched backup folders."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from unityscraper.domains.backups.watch_folders import WatchFolderService


def _item(path: str, title_id: str = "4D5307E6", size: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        path=Path(path), title_id=title_id, name=Path(path).name, format="STFS",
        content_type="DLC", size=size,
    )


class FakeScanner:
    """Return configured items per root; roots listed in ``failing`` raise."""

    def __init__(self) -> None:
        self.items: dict[str, list[SimpleNamespace]] = {}
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, root, title_lookup=None):
        self.calls.append(str(root))
        if str(root) in self.failing:
            raise OSError("drive unplugged")
        return SimpleNamespace(items=list(self.items.get(str(root), [])), warnings=[])


class WatchFolderServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.scanner = FakeScanner()
        self.service = WatchFolderService(self.temp_dir / "watch.db", scanner=self.scanner)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _folder(self, name: str):
        directory = self.temp_dir / name
        directory.mkdir()
        return self.service.add(directory, label=name)

    def test_add_rejects_non_directory_and_duplicates(self):
        file_path = self.temp_dir / "file.bin"
        file_path.write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.service.add(file_path)
        with self.assertRaises(ValueError):
            self.service.add(self.temp_dir / "missing")
        folder = self._folder("usb")
        with self.assertRaises(ValueError):
            self.service.add(self.temp_dir / "usb")
        self.assertEqual([f.id for f in self.service.list()], [folder.id])

    def test_first_scan_is_baseline_and_later_scans_report_only_new_paths(self):
        folder = self._folder("usb")
        self.scanner.items[folder.path] = [_item("a"), _item("b")]
        baseline = self.service.scan(folder.id)
        self.assertEqual(baseline.new_items, [])
        self.assertEqual(baseline.total_items, 2)
        self.assertEqual(baseline.folder.last_item_count, 2)
        self.assertEqual(baseline.folder.last_new_count, 0)
        self.assertEqual(self.service.recent_new_items(folder.id), [])

        time.sleep(0.02)  # coarse Windows clocks: keep first_seen_at strictly after created_at
        self.scanner.items[folder.path] = [_item("a"), _item("b", size=99), _item("c")]
        second = self.service.scan(folder.id)
        self.assertEqual([item["path"] for item in second.new_items], [str(Path("c"))])
        self.assertEqual(second.folder.last_new_count, 1)
        self.assertEqual(second.removed_count, 0)
        recent = self.service.recent_new_items(folder.id)
        self.assertEqual([item["path"] for item in recent], [str(Path("c"))])
        self.assertEqual(recent[0]["titleid"], "4D5307E6")

        third = self.service.scan(folder.id)
        self.assertEqual(third.new_items, [])

    def test_removed_items_are_deleted_and_counted(self):
        folder = self._folder("usb")
        self.scanner.items[folder.path] = [_item("a"), _item("b"), _item("c")]
        self.service.scan(folder.id)
        self.scanner.items[folder.path] = [_item("b")]
        result = self.service.scan(folder.id)
        self.assertEqual(result.removed_count, 2)
        self.assertEqual(result.total_items, 1)
        self.assertEqual(result.new_items, [])
        # A returning path counts as new again because its history was deleted.
        self.scanner.items[folder.path] = [_item("a"), _item("b")]
        self.assertEqual(len(self.service.scan(folder.id).new_items), 1)

    def test_scan_failure_is_recorded_and_reraised(self):
        folder = self._folder("usb")
        self.scanner.failing.add(folder.path)
        with self.assertRaises(OSError):
            self.service.scan(folder.id)
        stored = self.service.get(folder.id)
        self.assertEqual(stored.last_status, "failed")
        self.assertEqual(stored.last_error, "drive unplugged")
        self.assertIsNotNone(stored.last_scan_at)
        # The first successful scan after a failure is still the baseline.
        self.scanner.failing.clear()
        self.scanner.items[folder.path] = [_item("a")]
        result = self.service.scan(folder.id)
        self.assertEqual(result.new_items, [])
        self.assertEqual(result.folder.last_status, "ok")
        self.assertIsNone(result.folder.last_error)

    def test_scan_all_continues_past_failures_and_skips_disabled(self):
        broken = self._folder("broken")
        working = self._folder("working")
        disabled = self._folder("disabled")
        self.service.set_enabled(disabled.id, False)
        self.scanner.failing.add(broken.path)
        self.scanner.items[working.path] = [_item("a")]
        summary = self.service.scan_all()
        self.assertEqual([r.folder.id for r in summary.results], [working.id])
        self.assertEqual([(f.id, error) for f, error in summary.failures],
                         [(broken.id, "drive unplugged")])
        self.assertNotIn(disabled.path, self.scanner.calls)

    def test_remove_deletes_folder_items(self):
        folder = self._folder("usb")
        self.scanner.items[folder.path] = [_item("a")]
        self.service.scan(folder.id)
        self.service.remove(folder.id)
        self.assertEqual(self.service.list(), [])
        with self.service._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM watch_folder_items").fetchone()[0]
        self.assertEqual(count, 0)

    def test_run_if_due_respects_schedule(self):
        folder = self._folder("usb")
        self.scanner.items[folder.path] = [_item("a")]
        first = self.service.run_if_due()
        self.assertIsNotNone(first)
        self.assertEqual(len(first.results), 1)
        self.assertIsNone(self.service.run_if_due())
        self.assertEqual(len(self.scanner.calls), 1)
        self.service.schedule().configure(False, 12)
        with self.service._connect() as connection:
            connection.execute(
                "UPDATE scheduled_sync_state SET last_completed_at=NULL WHERE task_name=?",
                ("watch-folders",),
            )
        self.assertIsNone(self.service.run_if_due())
        self.assertEqual(len(self.scanner.calls), 1)


if __name__ == "__main__":
    unittest.main()
