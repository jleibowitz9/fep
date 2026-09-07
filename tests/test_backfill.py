"""The reconstructed 2025 season.

2025 exists as a season file so the CMS tables have a real season in them
before 2026 starts. It is reconstructed, so these tests exist to keep it honest:
the numbers stored must be the ones that were published, and it must sit
alongside 2026 without either touching the other.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fep import cms, engine, season as season_mod  # noqa: E402


def load(year):
    try:
        return season_mod.load(year)
    except FileNotFoundError:
        return None


class Backfill2025Test(unittest.TestCase):

    def setUp(self):
        self.season = load(2025)
        if self.season is None:
            self.skipTest("no 2025 season file; run scripts/backfill_2025.py")

    def test_the_season_matches_the_record(self):
        results = [g["result"] for g in self.season["games"]]
        self.assertEqual((results.count("W"), results.count("L")), (11, 6))
        self.assertEqual(sum(g["points_for"] for g in self.season["games"]), 379)
        self.assertEqual(self.season["bye_week"], 9)

    def test_pop_won_it_on_eleven(self):
        final = self.season["snapshots"][-1]["current_points"]
        best = max(final.values())
        self.assertEqual(best, 11)
        self.assertEqual([n for n, v in final.items() if v == best], ["Pop"])

    def test_the_standings_are_the_published_numbers(self):
        """Not recomputed. Recomputing drifts by up to 6.7 points mid-season,
        because ESPN's in-season lines were never kept."""
        path = os.path.join(ROOT, "chart-data", "2025", "week-18.json")
        if not os.path.exists(path):
            self.skipTest("no published 2025 chart data")
        with open(path) as fh:
            final = json.load(fh)
        rows = {r["slug"]: r for r in cms.tables(self.season)["standings"].rows}
        self.assertEqual(len(rows), 19 * 12)
        for entry in final["series"]:
            for week, value in zip(final["weeks"], entry["values"]):
                slug = "2025-w{:02d}-{}".format(week, entry["name"].lower())
                self.assertEqual(rows[slug]["weighted"], value, slug)

    def test_it_is_marked_as_reconstructed(self):
        """Nothing downstream should mistake this for a contemporaneous record."""
        self.assertTrue(self.season.get("reconstructed"))
        for snapshot in self.season["snapshots"]:
            self.assertTrue(snapshot.get("reconstructed"), snapshot["week"])
            self.assertIn("weights", snapshot["note"])

    def test_no_snapshot_sees_a_game_played_after_it(self):
        by_index = {g["index"]: g for g in self.season["games"]}
        for snapshot in self.season["snapshots"]:
            for index, result in enumerate(snapshot["results"]):
                if result != engine.UNPLAYED:
                    self.assertLessEqual(by_index[index]["nfl_week"],
                                         snapshot["week"])


class TwoSeasonsTest(unittest.TestCase):
    """2025 and 2026 share a spreadsheet and must not share a row."""

    def setUp(self):
        self.a, self.b = load(2025), load(2026)
        if self.a is None or self.b is None:
            self.skipTest("need both season files")

    def test_no_slug_collides(self):
        left, right = cms.tables(self.a), cms.tables(self.b)
        for name in left:
            if name == "competitors":
                continue          # spans seasons by design
            overlap = ({r["slug"] for r in left[name].rows} &
                       {r["slug"] for r in right[name].rows})
            self.assertEqual(overlap, set(), name)

    def test_the_shared_competitors_table_agrees(self):
        """Both seasons write it, so the last push must not undo the first."""
        left = {r["slug"]: r for r in cms.tables(self.a)["competitors"].rows}
        right = {r["slug"]: r for r in cms.tables(self.b)["competitors"].rows}
        self.assertEqual(sorted(left), sorted(right))
        for slug in left:
            self.assertEqual(left[slug]["color"], right[slug]["color"], slug)

    def test_every_table_has_the_same_columns_in_both_seasons(self):
        """A column that appears in one season and not the other breaks the
        header check on the second push."""
        left, right = cms.tables(self.a), cms.tables(self.b)
        for name in left:
            self.assertEqual(list(left[name].columns), list(right[name].columns),
                             name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
