"""The reconstructed 2025 season.

2025 exists as a season file so the CMS tables have a real season in them
before 2026 starts. It is reconstructed, so these tests exist to keep it honest:
the numbers stored must be the ones that were published, and it must sit
alongside 2026 without either touching the other.
"""

from __future__ import annotations

import contextlib
import io
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

    def test_the_shared_table_does_not_depend_on_who_is_pushing(self):
        """competitors is written by every season, so every season must agree
        about it. seasons_played once added one for a season not yet in
        history, so a 2025 push said 10 and a 2026 push said 11 and the two
        overwrote each other on every run."""
        left = {r["slug"]: r for r in cms.tables(self.a)["competitors"].rows}
        right = {r["slug"]: r for r in cms.tables(self.b)["competitors"].rows}
        for slug in set(left) & set(right):
            self.assertEqual(left[slug], right[slug], slug)

    def test_every_table_has_the_same_columns_in_both_seasons(self):
        """A column that appears in one season and not the other breaks the
        header check on the second push."""
        left, right = cms.tables(self.a), cms.tables(self.b)
        for name in left:
            self.assertEqual(list(left[name].columns), list(right[name].columns),
                             name)


class RealDataPassesTheGuardsTest(unittest.TestCase):
    """Run actual season data through the Apps Script's rules, in Python.

    The formula guard rejected "@ Chiefs" on the first real push, having
    survived every test on both sides: the Python tests never reached the
    script, and the JavaScript tests used made-up rows that happened never to
    start with "@". These close that gap by asserting the rules against every
    cell of every table of both real seasons.

    Mirrors appsscript/Code.gs. If that file's rules change, this must too, and
    the duplication is the point: it is a second pair of eyes on the same rule,
    not a shared implementation that can be wrong in one place.
    """

    import re as _re
    FORMULA = _re.compile(r"^[=+\-]")

    def seasons(self):
        found = [s for s in (load(2025), load(2026)) if s]
        if not found:
            self.skipTest("no season files")
        return found

    def test_no_real_cell_looks_like_a_formula(self):
        for season in self.seasons():
            for name, table in cms.tables(season).items():
                for row in table.matrix()[1:]:
                    for column, cell in zip(table.columns, row):
                        if isinstance(cell, str) and self.FORMULA.match(cell):
                            self.fail("{} {}.{} would be refused: {!r}".format(
                                season["year"], name, column, cell))

    def test_away_game_labels_survive(self):
        """The specific case that failed."""
        for season in self.seasons():
            labels = [r["label"] for r in cms.tables(season)["games"].rows]
            away = [l for l in labels if l.startswith("@")]
            self.assertTrue(away, "no away games to test")
            for label in away:
                self.assertIsNone(self.FORMULA.match(label), label)

    def test_no_cell_is_empty_where_a_slug_belongs(self):
        for season in self.seasons():
            for name, table in cms.tables(season).items():
                for row in table.rows:
                    self.assertTrue(row["slug"], "{} {}".format(season["year"], name))

    def test_column_a_is_always_the_slug(self):
        for season in self.seasons():
            for name, table in cms.tables(season).items():
                self.assertEqual(table.columns[0], "slug", name)


class ReproducibleTest(unittest.TestCase):
    """2025 must be rebuildable from a clean clone.

    The script reads an archive that lives outside this repository and fetches
    a schedule from a live ESPN that will not serve a 2025 predictor line
    forever. data/fixtures/2025_source.json is both of those written down, so
    the committed season file is an artefact anyone can reproduce rather than
    one that happened to exist on one laptop.
    """

    FIXTURE = os.path.join(ROOT, "data", "fixtures", "2025_source.json")

    def setUp(self):
        if not os.path.exists(self.FIXTURE):
            self.skipTest("no fixture; run scripts/backfill_2025.py --capture")

    def _module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backfill_2025", os.path.join(ROOT, "scripts", "backfill_2025.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_fixture_records_which_archive_it_came_from(self):
        with open(self.FIXTURE) as fh:
            fixture = json.load(fh)
        self.assertRegex(fixture["archive_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(fixture["games"]), 17)
        self.assertEqual(len(fixture["archive"]["picks_dict"]), 12)

    def test_the_weight_map_survives_a_json_round_trip(self):
        """JSON has no integer keys, so a weight map read back keyed by string
        sorts 0, 1, 10, 11, ... 2, 3, which reorders every win probability and
        moves every board. It moved the worst-case drift from 6.7 to 25.1."""
        module = self._module()
        weights = module.sources()["archive"]["weight"]
        self.assertEqual(sorted(weights), list(range(17)))
        self.assertTrue(all(isinstance(k, int) for k in weights))

    def test_it_rebuilds_with_no_archive_and_no_network(self):
        import urllib.request

        module = self._module()
        module.ARCHIVE = "/nonexistent/simulator.py"

        def unavailable(*args, **kwargs):
            raise AssertionError("reached outside the repository")

        # module.espn IS fep.espn, so this patch is global and has to be put
        # back or every later test that touches the schedule blows up.
        real_urlopen = urllib.request.urlopen
        real_fetch = module.espn.fetch_schedule
        urllib.request.urlopen = unavailable
        module.espn.fetch_schedule = unavailable
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rebuilt = module.build(write=False)
        finally:
            urllib.request.urlopen = real_urlopen
            module.espn.fetch_schedule = real_fetch

        committed = load(2025)
        if committed is None:
            self.skipTest("no committed 2025 season file")

        # Everything but the wall clock.
        def strip(season):
            season = json.loads(json.dumps(season))
            season.pop("updated_at", None)
            season.pop("created_at", None)
            for snapshot in season.get("snapshots", []):
                snapshot.pop("taken_at", None)
            return season

        self.assertEqual(strip(rebuilt), strip(committed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
