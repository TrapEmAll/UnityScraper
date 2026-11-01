"""Tests for library personal data, cover thumbnails and the library filter/sort logic."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from unityscraper.app.desktop.library_page import CHIPS, SORT_KEYS, filter_and_sort
from unityscraper.core.thumbnails import ThumbnailCache
from unityscraper.domains.library import GameSummary
from unityscraper.domains.library.user_data import (
    TAG_MAX_LENGTH,
    GameUserData,
    GameUserDataService,
)


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestGameUserData(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = GameUserDataService(self.temp_dir / "library.db")

    def test_defaults_without_row(self) -> None:
        self.assertEqual(self.service.get("4d5307e6"), GameUserData("4D5307E6"))
        self.assertEqual(self.service.get_many([]), {})

    def test_upserts_preserve_other_fields(self) -> None:
        self.service.set_favorite("4d5307e6", True)
        self.service.set_play_status("4D5307E6", "Playing")
        self.service.set_rating("4D5307E6", 4)
        self.service.set_notes("4D5307E6", "Finish the campaign")
        self.service.set_favorite("4D5307E6", False)
        data = self.service.get("4D5307E6")
        self.assertFalse(data.favorite)
        self.assertEqual(data.play_status, "Playing")
        self.assertEqual(data.rating, 4)
        self.assertEqual(data.notes, "Finish the campaign")
        self.service.set_rating("4D5307E6", None)
        self.assertIsNone(self.service.get("4D5307E6").rating)
        self.assertEqual(self.service.get("4D5307E6").notes, "Finish the campaign")

    def test_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            self.service.set_play_status("4D5307E6", "Beaten")
        for rating in (0, 6, 2.5, True):
            with self.assertRaises(ValueError):
                self.service.set_rating("4D5307E6", rating)  # type: ignore[arg-type]
        for tag in ("", "   ", "x" * (TAG_MAX_LENGTH + 1)):
            with self.assertRaises(ValueError):
                self.service.add_tag("4D5307E6", tag)
        with self.assertRaises(ValueError):
            self.service.set_favorite(" ", True)
        self.assertEqual(self.service.get("4D5307E6"), GameUserData("4D5307E6"))

    def test_tag_normalization_and_case_insensitive_uniqueness(self) -> None:
        self.assertEqual(self.service.add_tag("4D5307E6", "  Split   screen \t"), "Split screen")
        self.service.add_tag("4D5307E6", "split SCREEN")
        self.service.add_tag("4D5307E6", "Co-op")
        self.assertEqual(self.service.get("4D5307E6").tags, ("Co-op", "Split screen"))
        self.service.remove_tag("4D5307E6", "SPLIT  screen")
        self.assertEqual(self.service.get("4D5307E6").tags, ("Co-op",))

    def test_all_tags_counts_and_order(self) -> None:
        self.service.add_tag_many(["A", "B", "C"], "rpg")
        self.service.add_tag_many(["A", "B"], "Co-op")
        self.service.add_tag_many(["A", "B"], "arcade")
        self.service.add_tag("C", "RPG")  # duplicate of "rpg" for C
        self.assertEqual(self.service.all_tags(), [("rpg", 3), ("arcade", 2), ("Co-op", 2)])

    def test_bulk_operations(self) -> None:
        self.service.set_notes("A", "keep me")
        self.service.set_favorite_many(["a", "b"], True)
        self.service.set_play_status_many(["A", "B", "C"], "Backlog")
        self.service.add_tag_many(["a", "c"], "Halo")
        data = self.service.get_many(["A", "B", "C", "D"])
        self.assertEqual(set(data), {"A", "B", "C", "D"})
        self.assertTrue(data["A"].favorite and data["B"].favorite)
        self.assertFalse(data["C"].favorite)
        self.assertEqual({data[key].play_status for key in "ABC"}, {"Backlog"})
        self.assertEqual(data["A"].notes, "keep me")
        self.assertEqual(data["A"].tags, ("Halo",))
        self.assertEqual(data["B"].tags, ())
        self.assertEqual(data["D"], GameUserData("D"))
        self.assertEqual(self.service.favorite_count(), 2)
        with self.assertRaises(ValueError):
            self.service.set_play_status_many(["A"], "Nope")


class TestThumbnailCache(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cache = ThumbnailCache(self.temp_dir / "thumbs")
        self.source = self.temp_dir / "cover.jpg"
        Image.new("RGB", (400, 300), "red").save(self.source)

    def test_creates_exact_size_and_reuses_cache(self) -> None:
        first = self.cache.get(self.source, (150, 210))
        self.assertIsNotNone(first)
        assert first is not None
        with Image.open(first) as thumb:
            self.assertEqual(thumb.size, (150, 210))
        stamp = first.stat().st_mtime_ns
        second = self.cache.get(self.source, (150, 210))
        self.assertEqual(second, first)
        self.assertEqual(second.stat().st_mtime_ns, stamp)  # type: ignore[union-attr]
        self.assertNotEqual(self.cache.get(self.source, (60, 80)), first)
        self.assertEqual(list((self.temp_dir / "thumbs").glob("*.partial")), [])

    def test_source_change_invalidates(self) -> None:
        first = self.cache.get(self.source, (150, 210))
        Image.new("RGB", (100, 500), "blue").save(self.source)
        stat = self.source.stat()
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        second = self.cache.get(self.source, (150, 210))
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)

    def test_missing_or_broken_image_returns_none(self) -> None:
        self.assertIsNone(self.cache.get(self.temp_dir / "missing.png", (150, 210)))
        broken = self.temp_dir / "broken.png"
        broken.write_bytes(b"not an image")
        self.assertIsNone(self.cache.get(broken, (150, 210)))


def _game(titleid: str, name: str, **values: object) -> GameSummary:
    fields: dict[str, object] = {
        "publisher": "",
        "last_scraped": "",
        "covers_total": 0,
        "covers_downloaded": 0,
        "updates_total": 0,
        "updates_downloaded": 0,
        "updates_failed": 0,
    }
    fields.update(values)
    return GameSummary(titleid=titleid, name=name, **fields)  # type: ignore[arg-type]


class TestFilterAndSort(unittest.TestCase):
    def setUp(self) -> None:
        self.games = [
            _game("AAAA0001", "Halo 3", publisher="Microsoft", last_scraped="2026-01-03",
                  updates_total=2, updates_downloaded=2),
            _game("aaaa0002", "alan wake", publisher="Remedy", last_scraped="2026-01-01",
                  updates_total=3, updates_downloaded=1),
            _game("AAAA0003", "Crackdown", publisher="Microsoft", last_scraped="2026-01-02",
                  updates_total=1, updates_downloaded=0, updates_failed=1),
            _game("AAAA0004", "Braid", publisher="Number None"),
        ]
        self.data = {
            "AAAA0001": GameUserData("AAAA0001", favorite=True, play_status="Completed",
                                     tags=("Shooter", "Co-op")),
            "AAAA0002": GameUserData("AAAA0002", play_status="Playing", tags=("story",)),
        }
        self.watched = {"aaaa0003"}

    def ids(self, **options: object) -> list[str]:
        return [
            game.titleid
            for game in filter_and_sort(self.games, self.data, self.watched, **options)
        ]

    def test_chips(self) -> None:
        expected = {
            "All": ["aaaa0002", "AAAA0004", "AAAA0003", "AAAA0001"],
            "Favorites": ["AAAA0001"],
            "Needs updates": ["aaaa0002", "AAAA0003"],
            "Complete": ["AAAA0001"],
            "Needs attention": ["AAAA0003"],
            "Watched": ["AAAA0003"],
        }
        self.assertEqual(set(expected), set(CHIPS))
        for chip, ids in expected.items():
            with self.subTest(chip=chip):
                self.assertEqual(self.ids(chip=chip), ids)
        with self.assertRaises(ValueError):
            self.ids(chip="Bogus")

    def test_play_status_and_tag_filters(self) -> None:
        self.assertEqual(self.ids(play_status="Playing"), ["aaaa0002"])
        self.assertEqual(self.ids(play_status=""), ["AAAA0004", "AAAA0003"])
        self.assertEqual(self.ids(tag="co-op"), ["AAAA0001"])
        self.assertEqual(self.ids(tag="co-op", play_status="Playing"), [])
        self.assertEqual(len(self.ids(tag=None, play_status=None)), 4)

    def test_sort_keys(self) -> None:
        expected = {
            "Name": ["aaaa0002", "AAAA0004", "AAAA0003", "AAAA0001"],
            "TitleID": ["AAAA0001", "aaaa0002", "AAAA0003", "AAAA0004"],
            "Publisher": ["AAAA0003", "AAAA0001", "AAAA0004", "aaaa0002"],
            "Updates": ["AAAA0004", "AAAA0003", "AAAA0001", "aaaa0002"],
            "Last scraped": ["AAAA0004", "aaaa0002", "AAAA0003", "AAAA0001"],
        }
        self.assertEqual(set(expected), set(SORT_KEYS))
        for key, ids in expected.items():
            with self.subTest(sort_key=key):
                self.assertEqual(self.ids(sort_key=key), ids)
                if key != "Publisher":  # Publisher has ties; covered by the test below.
                    self.assertEqual(self.ids(sort_key=key, descending=True), ids[::-1])
        self.assertEqual(self.ids(sort_key="Favorite", descending=True)[0], "AAAA0001")
        self.assertEqual(self.ids(sort_key="Play status")[-1], "AAAA0001")
        with self.assertRaises(ValueError):
            self.ids(sort_key="Size")

    def test_descending_ties_keep_name_order(self) -> None:
        self.assertEqual(
            self.ids(sort_key="Publisher", descending=True),
            ["aaaa0002", "AAAA0004", "AAAA0003", "AAAA0001"],
        )


if __name__ == "__main__":
    unittest.main()
