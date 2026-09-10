"""
The front-end fixture is reproducible, and depends on nothing that moves.

`dashboard/sample-data.json` is a full dashboard payload for a week that has not
happened, so the front end can be worked on out of season. Its whole value rests
on two claims, and until the September 2026 review neither was checked here:

  It regenerates byte for byte. `make_fixture.py --check` said otherwise and
  nothing in the suite ran it, so it had been failing silently.

  It is built from nothing mutable. It used to read the live season file, which
  moves twice over -- pick sheets arrive through September, and `refresh` pulls
  new ESPN weights every week while the seeded coin flips are
  `rng.random() < weight`. So the check broke on a schedule, roughly every
  Sunday, however recently it had been regenerated. Regenerating it was never
  the fix; freezing its inputs was.

  TestFixtureIsReproducible   the committed file matches a fresh generation
  TestFixtureInputsAreFrozen  and nothing live can reach it
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD = os.path.join(ROOT, "dashboard")
sys.path.insert(0, ROOT)
sys.path.insert(0, DASHBOARD)

spec = importlib.util.spec_from_file_location(
    "make_fixture", os.path.join(DASHBOARD, "make_fixture.py"))
make_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_fixture)

from fep import season as season_mod  # noqa: E402


class TestFixtureIsReproducible(unittest.TestCase):
    """What `--check` asks, asked where it cannot be forgotten."""

    def test_the_committed_fixture_matches_a_fresh_generation(self):
        built = make_fixture.build_fixture()
        expected = json.dumps(built, indent=1, sort_keys=True) + "\n"
        with open(make_fixture.OUTPUT) as fh:
            self.assertEqual(
                fh.read(), expected,
                "dashboard/sample-data.json is stale. Regenerate it:\n"
                "  python3 dashboard/make_fixture.py")


class TestFixtureInputsAreFrozen(unittest.TestCase):
    """Nothing that changes on its own is allowed to reach the fixture."""

    def setUp(self):
        with open(make_fixture.INPUTS) as fh:
            self.frozen = json.load(fh)

    def test_the_frozen_inputs_are_committed(self):
        self.assertTrue(os.path.exists(make_fixture.INPUTS))

    def test_no_real_pick_sheets_are_frozen_into_it(self):
        # Twelve real people's actual predictions have no business in a
        # synthetic season, and picks arriving through September were half the
        # reason the check kept failing.
        self.assertNotIn("picks", self.frozen)
        self.assertNotIn("points_guess", self.frozen)

    def test_building_never_reads_the_live_season_file(self):
        def refuse(year):
            self.fail("the fixture read data/season_{}.json".format(year))
        original = season_mod.load
        season_mod.load = refuse
        try:
            make_fixture.build_fixture()
        finally:
            season_mod.load = original

    def test_a_moved_espn_weight_does_not_change_the_fixture(self):
        # The failure mode that broke this every Sunday.
        before = make_fixture.build_fixture()
        live = season_mod.load(2026)
        live["games"][5]["weight"] = 0.777
        original = season_mod.load
        season_mod.load = lambda year: live
        try:
            self.assertEqual(make_fixture.build_fixture(), before)
        finally:
            season_mod.load = original

    def test_the_frozen_schedule_still_matches_the_live_one(self):
        # Not reproducibility -- provenance. A fixture built against last
        # season's schedule regenerates perfectly and tests nothing useful, so
        # this is the tap on the shoulder to run --refresh-inputs.
        live = season_mod.load(self.frozen["year"])
        self.assertEqual([g["label"] for g in self.frozen["games"]],
                         [g["label"] for g in live["games"]],
                         "the frozen schedule has drifted from the season "
                         "file. Refresh it:\n"
                         "  python3 dashboard/make_fixture.py --refresh-inputs")
        self.assertEqual(self.frozen["roster"], live["roster"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
