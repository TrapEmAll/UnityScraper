"""Ranking tests for the desktop command palette (no Tk window is created)."""

from __future__ import annotations

import unittest

from unityscraper.app.desktop.command_palette import PaletteEntry, fuzzy_score, rank


def entry(title: str, subtitle: str = "", keywords: str = "", kind: str = "Page") -> PaletteEntry:
    return PaletteEntry(title, kind, lambda: None, subtitle=subtitle, keywords=keywords)


class FuzzyScoreTests(unittest.TestCase):
    def test_non_subsequence_returns_none(self) -> None:
        self.assertIsNone(fuzzy_score("xyz", "Library"))
        self.assertIsNone(fuzzy_score("bil", "Library"))  # right letters, wrong order
        self.assertIsNone(fuzzy_score("libraryy", "Library"))
        self.assertIsNone(fuzzy_score("a", ""))

    def test_case_and_whitespace_insensitive(self) -> None:
        self.assertIsNotNone(fuzzy_score("LIB", "library"))
        self.assertIsNotNone(fuzzy_score("add game", "AddGames"))
        self.assertEqual(fuzzy_score("  ", "Library"), 0.0)

    def test_prefix_beats_middle(self) -> None:
        self.assertGreater(fuzzy_score("lib", "Library"), fuzzy_score("lib", "Alibrary"))

    def test_word_start_beats_mid_word(self) -> None:
        self.assertGreater(fuzzy_score("gl", "Game Library"), fuzzy_score("gl", "Giggles"))
        self.assertGreater(fuzzy_score("ag", "Add Games"), fuzzy_score("ag", "Bags"))
        self.assertGreater(fuzzy_score("pl", "PackageLab"), fuzzy_score("pl", "Pxxxxlxxxx"))

    def test_contiguous_beats_scattered(self) -> None:
        self.assertGreater(fuzzy_score("abc", "abcxyz"), fuzzy_score("abc", "axbxcx"))
        # The best alignment is found, not just the leftmost one.
        self.assertGreater(fuzzy_score("game", "go a game"), fuzzy_score("game", "gxaxmxex"))

    def test_shorter_text_wins_ties(self) -> None:
        self.assertGreater(fuzzy_score("lib", "Library"), fuzzy_score("lib", "Library Settings"))

    def test_scores_are_non_negative(self) -> None:
        self.assertGreaterEqual(fuzzy_score("z", "a" * 500 + "z"), 0.0)


class RankTests(unittest.TestCase):
    def test_empty_query_keeps_order_and_limit(self) -> None:
        entries = [entry(f"Item {index}") for index in range(10)]
        self.assertEqual(rank("", entries), entries)
        self.assertEqual(rank("   ", entries, limit=3), entries[:3])

    def test_drops_non_matches_and_orders_by_score(self) -> None:
        downloads, library, settings = entry("Downloads"), entry("Library"), entry("Settings")
        lab = entry("Package Lab")
        self.assertEqual(rank("lib", [downloads, settings, library]), [library])
        self.assertEqual(rank("la", [lab, library]), [library, lab])
        self.assertEqual(rank("lab", [library, lab]), [lab])

    def test_limit_applies_after_ranking(self) -> None:
        entries = [entry("Zebra library"), entry("Library"), entry("Lib")]
        self.assertEqual(rank("lib", entries, limit=2), [entries[2], entries[1]])

    def test_ties_are_stable(self) -> None:
        first, second, third = entry("Backups"), entry("Backups"), entry("Backups")
        self.assertEqual(rank("back", [first, second, third]), [first, second, third])
        self.assertEqual(rank("back", [third, first, second]), [third, first, second])

    def test_subtitle_and_keyword_matches_rank_below_title_matches(self) -> None:
        by_subtitle = entry("Settings", subtitle="Backups and restore")
        by_keyword = entry("Profiles", keywords="backups saves")
        by_title = entry("Backups")
        ranked = rank("backups", [by_subtitle, by_keyword, by_title])
        self.assertEqual(ranked[0], by_title)
        self.assertEqual(set(ranked[1:]), {by_subtitle, by_keyword})


if __name__ == "__main__":
    unittest.main()
