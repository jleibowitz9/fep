"""
Regression tests for the September 2026 external review.

Each test here is pinned to one finding. They are kept in their own file rather
than folded into test_engine.py so that the mapping from "a reviewer found X"
to "X cannot come back" stays legible.

  TestSeasonEndTiebreaker    tiebreaker 3 stayed probabilistic after the season
                             was over, and could crown the wrong champion
  TestTies                   a real NFL tie was scored as an Eagles loss
  TestElimination            "mathematically eliminated" was read off the
                             weighted board, which measures odds, not rules
  TestValidationHoles        scores, guesses and the model name went unchecked
  TestHistoricalBuilds       a past week's board shipped beside future data
  TestPayloadContract        the fixture had a key the live builder never made
  TestPreseason              a week 0 payload crashed the front end
  TestByeWeekResolution      the default weekly run read the week off the
                             scoreboard, which skips the bye entirely
  TestSnapshotsFreeze        a snapshot documented as frozen replaced itself
                             on every re-run, and a moved weight rewrote a
                             week that had already been published
  TestPublishedWeeksFreeze   the same, for the chart file behind a URL that
                             has already gone out
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fep import (analytics, chart, engine, espn, publish,  # noqa: E402
                 season as season_mod)

DASHBOARD = os.path.join(ROOT, "dashboard")


def load_build():
    sys.path.insert(0, DASHBOARD)
    spec = importlib.util.spec_from_file_location(
        "dashboard_build", os.path.join(DASHBOARD, "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def one_game_season(guess_a, guess_b, result="W", score=None):
    return dict(
        picks={"A": [result], "B": [result]},
        results=[result],
        weights=[None],
        division_indices=[],
        points_guess={"A": guess_a, "B": guess_b},
        points_scored=[score],
    )


# ---------------------------------------------------------------------------
# Finding 3: the final points tiebreaker stayed probabilistic
# ---------------------------------------------------------------------------

class TestSeasonEndTiebreaker(unittest.TestCase):

    def test_a_known_total_is_decided_not_sampled(self):
        """The reviewer's exact case: actual 10, guesses 10 and 12.

        The old engine clamped sd to 1 and handed the 10-guess 84.1%. Ten is the
        total. There is nothing left to be uncertain about.
        """
        board = engine.run(**one_game_season(10, 12, score=10))
        self.assertEqual(board.weighted["A"], 100.0)
        self.assertEqual(board.weighted["B"], 0.0)

    def test_equally_distant_guesses_split(self):
        board = engine.run(**one_game_season(8, 12, score=10))
        self.assertAlmostEqual(board.weighted["A"], 50.0)
        self.assertAlmostEqual(board.weighted["B"], 50.0)

    def test_the_nearer_guess_wins_from_either_side(self):
        below = engine.run(**one_game_season(9, 20, score=10))
        self.assertEqual(below.weighted["A"], 100.0)
        above = engine.run(**one_game_season(1, 11, score=10))
        self.assertEqual(above.weighted["B"], 100.0)

    def test_an_unfinished_season_stays_probabilistic(self):
        """The deterministic branch must not leak into a live week.

        Both guesses straddle the projected total, so a probabilistic
        tiebreaker has to give each of them a real share. The exact branch
        would hand one of them everything.
        """
        board = engine.run(
            picks={"A": ["W", "W"], "B": ["W", "W"]},
            results=["W", "A"], weights=[None, 0.5], division_indices=[],
            points_guess={"A": 40, "B": 55}, points_scored=[24, None])
        self.assertFalse(board.points["exact"])
        for name in ("A", "B"):
            self.assertGreater(board.weighted[name], 1.0)
            self.assertLess(board.weighted[name], 99.0)

    def test_a_finished_season_missing_a_score_is_not_exact(self):
        """Every game played is not enough; the total has to be known."""
        board = engine.run(**one_game_season(10, 12, score=None))
        self.assertFalse(board.points["exact"])

    def test_an_unscored_played_game_is_projected_not_zeroed(self):
        """Summing only the scores we have under-projects the season.

        Two played games and one score used to mean "the season total is that
        one score", which dragged the whole tiebreaker down.
        """
        model = engine.points_distribution(["W", "W"], [24, None])
        self.assertGreater(model["mean"], 24.0)
        self.assertGreater(model["sd"], 1.0)


# ---------------------------------------------------------------------------
# Finding 6: a real NFL tie could not be represented
# ---------------------------------------------------------------------------

class TestTies(unittest.TestCase):

    def test_a_tie_is_a_valid_result(self):
        engine.validate({"A": ["W", "L"]}, ["T", "A"], [None, 0.5], [], {"A": 400})

    def test_a_tie_credits_nobody(self):
        board = engine.run(
            picks={"A": ["W", "W"], "B": ["L", "W"]},
            results=["T", "A"], weights=[None, 0.5], division_indices=[],
            points_guess={"A": 400, "B": 420})
        self.assertEqual(board.current_points, {"A": 0, "B": 0})

    def test_a_tie_is_settled_so_it_is_not_enumerated(self):
        board = engine.run(
            picks={"A": ["W", "W"], "B": ["L", "W"]},
            results=["T", "A"], weights=[None, 0.5], division_indices=[],
            points_guess={"A": 400, "B": 420})
        self.assertEqual(board.remaining_outcomes, 2)

    def test_a_tie_is_not_a_win_for_the_record_tiebreaker(self):
        """Both sheets score 1. A predicted 2-0 is further from a 1-0-1 season
        than a predicted 1-1, so the tie must not count toward actual wins."""
        board = engine.run(
            picks={"AllWin": ["W", "W"], "Split": ["W", "L"]},
            results=["W", "T"], weights=[None, None], division_indices=[],
            points_guess={"AllWin": 400, "Split": 400}, points_scored=[24, 20])
        self.assertEqual(board.weighted["Split"], 100.0)

    def test_espn_reads_a_tie_as_a_tie(self):
        """A completed game where neither side carries `winner: True`.

        Testing `winner is False` alone turned this into an Eagles loss.
        """
        payload = {"events": [{"competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"team": {"abbreviation": "PHI"}, "winner": False,
                 "homeAway": "home", "score": "23"},
                {"team": {"abbreviation": "CIN", "shortDisplayName": "Bengals"},
                 "winner": False, "homeAway": "away", "score": "23"},
            ]}]}]}
        games = espn.parse_schedule(payload)
        self.assertEqual(games[0]["result"], "T")

    def test_espn_still_reads_a_loss_as_a_loss(self):
        payload = {"events": [{"competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"team": {"abbreviation": "PHI"}, "winner": False,
                 "homeAway": "home", "score": "17"},
                {"team": {"abbreviation": "DAL", "shortDisplayName": "Cowboys"},
                 "winner": True, "homeAway": "away", "score": "24"},
            ]}]}]}
        games = espn.parse_schedule(payload)
        self.assertEqual(games[0]["result"], "L")


# ---------------------------------------------------------------------------
# Finding 7: elimination read probability instead of possibility
# ---------------------------------------------------------------------------

class TestElimination(unittest.TestCase):

    def board_with_a_certain_game(self):
        return engine.run(
            picks={"A": ["W"], "B": ["L"]}, results=["A"], weights=[1.0],
            division_indices=[], points_guess={"A": 400, "B": 420})

    def test_a_zero_probability_competitor_is_not_eliminated(self):
        """Weight 1.0 gives B no equity, but B wins the outcome where the
        Eagles lose, and that outcome is structurally possible."""
        board = self.board_with_a_certain_game()
        self.assertEqual(board.weighted["B"], 0.0)
        self.assertGreater(board.straight["B"], 0.0)
        self.assertEqual(board.eliminated(), [])

    def test_that_competitor_is_reported_as_effectively_eliminated(self):
        board = self.board_with_a_certain_game()
        self.assertEqual(board.effectively_eliminated(), ["B"])

    def test_a_competitor_who_wins_nothing_is_eliminated(self):
        """Identical sheets, and B loses every tiebreaker outright."""
        board = engine.run(
            picks={"A": ["W", "W"], "B": ["W", "W"]},
            results=["W", "W"], weights=[None, None], division_indices=[],
            points_guess={"A": 44, "B": 400}, points_scored=[24, 20])
        self.assertEqual(board.eliminated(), ["B"])
        self.assertEqual(board.effectively_eliminated(), [])


# ---------------------------------------------------------------------------
# Finding 8: validation holes
# ---------------------------------------------------------------------------

class TestValidationHoles(unittest.TestCase):

    def base(self, **over):
        kw = dict(picks={"A": ["W", "W"]}, results=["W", "A"],
                  weights=[None, 0.5], division_indices=[],
                  points_guess={"A": 400})
        kw.update(over)
        return kw

    def test_a_non_numeric_points_guess_is_rejected(self):
        with self.assertRaises(engine.SeasonError):
            engine.run(**self.base(points_guess={"A": "400"}))

    def test_a_non_finite_points_guess_is_rejected(self):
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(engine.SeasonError):
                engine.run(**self.base(points_guess={"A": bad}))

    def test_the_score_list_must_match_the_season_length(self):
        with self.assertRaises(engine.SeasonError):
            engine.run(**self.base(points_scored=[24]))

    def test_a_score_on_an_unplayed_game_is_rejected(self):
        with self.assertRaises(engine.SeasonError):
            engine.run(**self.base(points_scored=[24, 30]))

    def test_a_negative_score_is_rejected(self):
        with self.assertRaises(engine.SeasonError):
            engine.run(**self.base(points_scored=[-5, None]))

    def test_an_unknown_points_model_is_rejected(self):
        """A typo used to run the shrunk branch and then report itself as the
        model name, so it looked like a deliberate choice downstream."""
        with self.assertRaises(engine.SeasonError):
            engine.run(**self.base(points_model="shrunkk"))

    def test_the_two_real_models_are_still_accepted(self):
        for model in ("shrunk", "legacy"):
            engine.run(**self.base(points_model=model))


# ---------------------------------------------------------------------------
# Finding 5: historical builds mixed past boards with future data
# ---------------------------------------------------------------------------

class TestHistoricalBuilds(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.season = season_mod.load(2025)

    def test_pin_drops_later_snapshots(self):
        pinned = analytics.pin(self.season, 3)
        self.assertTrue(all(s["week"] <= 3 for s in pinned["snapshots"]))

    def test_pin_masks_later_games(self):
        pinned = analytics.pin(self.season, 3)
        for game in pinned["games"]:
            if game["nfl_week"] > 3:
                self.assertEqual(game["result"], engine.UNPLAYED)
                self.assertIsNone(game["points_for"])

    def test_volatility_cannot_read_the_future(self):
        """A week 1 pack used to report week 2's number as "current"."""
        board = season_mod.run(self.season, through_week=1)
        pack = analytics.full_pack(self.season, board, 1, through_week=1)
        week1 = next(s for s in self.season["snapshots"] if s["week"] == 1)
        for name, row in pack["volatility"].items():
            self.assertAlmostEqual(row["current"], round(week1["weighted"][name], 1))

    def test_retrospective_leverage_stops_at_the_pinned_week(self):
        board = season_mod.run(self.season, through_week=2)
        pack = analytics.full_pack(self.season, board, 2, through_week=2)
        self.assertEqual(len(pack["retrospective_leverage"]), 2)

    def test_a_historical_payload_ships_no_future_result(self):
        build = load_build()
        original = season_mod.load
        season_mod.load = lambda year: self.season
        try:
            data = build.collect(2025, 4)
        finally:
            season_mod.load = original
        for game in data["games"]:
            if game["week"] > 4:
                self.assertEqual(game["result"], engine.UNPLAYED)
        self.assertTrue(all(s["week"] <= 4 for s in data["snapshots"]))


# ---------------------------------------------------------------------------
# Findings 1 and 9: the fixture and the live builder must agree
# ---------------------------------------------------------------------------

class TestPayloadContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DASHBOARD, "sample-data.json")) as fh:
            cls.fixture = json.load(fh)
        build = load_build()
        original = season_mod.load
        season_mod.load = lambda year: season_mod.load.__wrapped__(2025)
        season_mod.load.__wrapped__ = original
        try:
            cls.live = build.collect(2025, 5)
        finally:
            season_mod.load = original

    def test_the_fixture_has_no_key_the_builder_cannot_produce(self):
        """The fixture's `whatif` key existed only in the mock, so the What If
        tab worked in development and failed against every live build."""
        extra = set(self.fixture) - set(self.live) - {"fixture"}
        self.assertEqual(extra, set())

    def test_the_builder_produces_every_key_the_fixture_has(self):
        missing = set(self.fixture) - {"fixture"} - set(self.live)
        self.assertEqual(missing, set())

    def test_the_live_payload_carries_a_whatif_board_per_game(self):
        self.assertEqual(len(self.live["whatif"]), len(self.live["games"]))
        for entry in self.live["whatif"].values():
            self.assertIn("W", entry)
            self.assertIn("L", entry)
            self.assertEqual(set(entry["W"]), set(self.live["roster"]))

    def test_dashboard_colors_come_from_the_chart_palette(self):
        self.assertEqual(self.live["colors"],
                         chart.colors_for(self.live["roster"]))

    def test_the_fixture_declares_itself_synthetic(self):
        """It holds final results for games dated after its own generation
        date. That is fine, but it has to say so."""
        self.assertTrue(self.fixture["fixture"]["synthetic"])

    def test_json_for_a_script_block_cannot_close_the_tag(self):
        build = load_build()
        payload = {"roster": ["</script><img src=x onerror=alert(1)>"]}
        rendered = build.script_json(payload)
        self.assertNotIn("</script>", rendered)
        self.assertEqual(json.loads(rendered), payload)


# ---------------------------------------------------------------------------
# Finding 2: a week 0 dashboard crashed on load
# ---------------------------------------------------------------------------

class TestPreseason(unittest.TestCase):
    """The live season sits at week 0 until the opener, and every sheet is in
    before then, so this is the first page the family will actually open."""

    @classmethod
    def setUpClass(cls):
        season = season_mod.load(2025)
        games = len(season["games"])
        for game in season["games"]:
            game["result"] = engine.UNPLAYED
            game["points_for"] = None
        season["snapshots"] = []
        cls.season = season
        cls.games = games

        build = load_build()
        original = season_mod.load
        season_mod.load = lambda year: season
        try:
            cls.data = build.collect(2025, 0)
        finally:
            season_mod.load = original
        cls.page = build.build(cls.data, os.path.join(
            os.environ.get("TMPDIR", "/tmp"), "fep-preseason-test.html"))

    def test_a_week_zero_payload_builds(self):
        self.assertEqual(self.data["week"], 0)
        self.assertEqual(self.data["snapshots"], [])

    def test_nothing_is_played(self):
        self.assertTrue(all(g["result"] == engine.UNPLAYED
                            for g in self.data["games"]))

    def test_heat_check_is_empty_rather_than_absent(self):
        """The front end reads D.heat.deltas unconditionally."""
        self.assertIn("deltas", self.data["heat"])
        self.assertEqual(self.data["heat"]["deltas"], {})

    def test_every_competitor_is_still_alive(self):
        self.assertEqual(self.data["elim"]["eliminated"], [])

    def test_the_page_guards_the_last_played_game(self):
        """`played[played.length-1].result` was dereferenced three times with
        no games played, which blanked the whole page."""
        with open(self.page) as fh:
            html = fh.read()
        self.assertNotIn("played[played.length-1].result", html)
        self.assertIn("const PRESEASON", html)

    def test_the_page_makes_no_claim_about_operations_it_did_not_run(self):
        """The Run screen asserted an ESPN fetch, a weight refresh, a saved
        snapshot, a published chart and a verified Sheet range. `cli.py
        dashboard` does none of those."""
        with open(self.page) as fh:
            html = fh.read()
        for invented in ("win probabilities refreshed",
                         "Sheet columns still match the roster",
                         "Saved snapshot",
                         "Prototype: no write performed"):
            self.assertNotIn(invented, html)

    def test_the_sparkline_survives_a_single_snapshot(self):
        """One snapshot divided by vals.length - 1."""
        with open(self.page) as fh:
            html = fh.read()
        self.assertIn("if(vals.length<2)", html)


# ---------------------------------------------------------------------------
# Review item 5: a harness that runs the page, and chart-renderer parity
# ---------------------------------------------------------------------------

class TestBrowserSmoke(unittest.TestCase):
    """Run the built page's own JavaScript and fail on anything it throws.

    tests/smoke_dashboard.js explains why this is a DOM stub under node rather
    than a real browser. In short: the failure worth catching was a load-time
    TypeError, which needs the page's code and the page's data but no layout.
    """

    @classmethod
    def setUpClass(cls):
        import shutil
        cls.node = shutil.which("node")

    def build_page(self, week, wipe_results):
        import tempfile
        build = load_build()
        season = season_mod.load(2025)
        if wipe_results:
            for game in season["games"]:
                game["result"] = engine.UNPLAYED
                game["points_for"] = None
            season["snapshots"] = []
        original = season_mod.load
        season_mod.load = lambda year: season
        try:
            data = build.collect(2025, week)
        finally:
            season_mod.load = original
        out = os.path.join(tempfile.gettempdir(),
                           "fep-smoke-{}.html".format(week))
        return build.build(data, out)

    def run_smoke(self, page):
        import subprocess
        script = os.path.join(ROOT, "tests", "smoke_dashboard.js")
        return subprocess.run([self.node, script, page],
                              capture_output=True, text=True)

    def test_a_preseason_page_initialises(self):
        """The week 0 page used to render a sidebar and an empty body."""
        if not self.node:
            self.skipTest("node is not installed")
        result = self.run_smoke(self.build_page(0, wipe_results=True))
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)

    def test_a_midseason_page_initialises(self):
        if not self.node:
            self.skipTest("node is not installed")
        result = self.run_smoke(self.build_page(5, wipe_results=False))
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)


class TestChartParity(unittest.TestCase):
    """The Python chart and the Framer component must mark games the same way.

    Published week-00.json files carry a null game for the preseason column.
    chart.py skips a result-less game unless it is labelled "Bye"; FEPChart.tsx
    treated every result-less game as a bye and drew a badge, so Framer showed
    an erroneous bye marker under P.

    This is a source-level assertion, not a rendering comparison: it checks
    that both files encode the same rule. A real pixel comparison would need
    both renderers running in a browser, which is the half of review item 5
    this does not cover.
    """

    def read(self, relative):
        with open(os.path.join(ROOT, relative)) as fh:
            return fh.read()

    def test_python_only_treats_a_labelled_bye_as_a_bye(self):
        source = self.read("fep/chart.py")
        self.assertIn("gm.label !== 'Bye'", source)

    def test_framer_only_treats_a_labelled_bye_as_a_bye(self):
        source = self.read("framer/FEPChart.tsx")
        self.assertIn('gm.label === "Bye"', source)
        self.assertNotIn("const bye = !gm.result", source)

    def test_framer_skips_an_unplayed_game_entirely(self):
        source = self.read("framer/FEPChart.tsx")
        self.assertIn("if (!gm.result && !bye) return null", source)

    def test_a_published_week_zero_has_a_null_preseason_game(self):
        """The condition both renderers have to agree about."""
        published = os.path.join(ROOT, "chart-data", "2025")
        if not os.path.isdir(published):
            self.skipTest("no published chart data")
        files = sorted(f for f in os.listdir(published) if f.endswith(".json"))
        if not files:
            self.skipTest("no published chart data")
        with open(os.path.join(published, files[0])) as fh:
            data = json.load(fh)
        first = data["games"][0]
        self.assertEqual(first["week"], 0)
        self.assertIsNone(first["result"])
        self.assertIsNone(first["label"])


# ---------------------------------------------------------------------------
# Redesign regressions: two ways a surface can disagree with the model
# ---------------------------------------------------------------------------

class TestRedesignSurfaces(unittest.TestCase):
    """Both of these read correct data and then said the wrong thing about it.

    They are the same underlying mistake in different clothes: a number shown
    on the page has to come from the thing its label claims, and a season
    constant has to come from the season.
    """

    def read_template(self):
        with open(os.path.join(DASHBOARD, "template.html")) as fh:
            return fh.read()

    def read_code(self):
        """The template with // line comments stripped.

        These assertions are about what the page executes, not what it
        explains about itself -- a comment naming the old expression is
        documentation, not a regression.
        """
        out = []
        for raw in self.read_template().split("\n"):
            marker = raw.find("//")
            # Leave URLs (https://) and anything inside a string alone; the
            # only // this file uses outside those is a real line comment.
            if marker != -1 and not raw[:marker].rstrip().endswith(":"):
                raw = raw[:marker]
            out.append(raw)
        return "\n".join(out)

    def test_still_alive_does_not_count_probability(self):
        """`conc.alive` is sum(weighted > 0) -- the effectively-eliminated
        notion. The card claiming "mathematical paths" must not source it."""
        code = self.read_code()
        self.assertNotIn("D.conc.alive", code)
        self.assertIn("D.roster.length - D.elim.eliminated.length", code)

    def test_still_alive_and_mathematical_elimination_agree(self):
        """The number the card shows and the list the obituary prints are two
        views of one fact, so they cannot disagree."""
        board = engine.run(
            picks={"A": ["W"], "B": ["L"]}, results=[engine.UNPLAYED],
            weights=[1.0], division_indices=[],
            points_guess={"A": 400, "B": 420})
        conc = analytics.concentration(board)
        alive = len(board.order) - len(board.eliminated())
        self.assertEqual(alive, 2)
        self.assertEqual(conc["alive"], 1)
        self.assertNotEqual(alive, conc["alive"])

    def test_division_games_are_not_hardcoded(self):
        """[0,6,7,8,10,16] is 2026's schedule and nothing else. The payload
        carries the flag per game; the division record is tiebreaker 2."""
        code = self.read_code()
        self.assertNotIn("[0,6,7,8,10,16]", code)
        self.assertIn("D.games.filter(g=>g.division)", code)

    def test_the_hardcoded_indices_were_wrong_for_a_real_season(self):
        """Proof the constant could not just be left alone."""
        season = season_mod.load(2025)
        actual = [g["index"] for g in season["games"] if g["division"]]
        self.assertNotEqual(actual, [0, 6, 7, 8, 10, 16])

    def test_the_payload_carries_a_division_flag_per_game(self):
        build = load_build()
        season = season_mod.load(2025)
        original = season_mod.load
        season_mod.load = lambda year: season
        try:
            data = build.collect(2025, 5)
        finally:
            season_mod.load = original
        flagged = [g["i"] for g in data["games"] if g["division"]]
        self.assertEqual(flagged,
                         [g["index"] for g in season["games"] if g["division"]])


# ---------------------------------------------------------------------------
# September 2026, finding 2: the default weekly run skipped the Week 10 bye
# ---------------------------------------------------------------------------

def bye_season(bye_week=10, last_week=18):
    """A schedule with one bye, dated a week apart, and nothing played yet."""
    games, index, date = [], 0, None
    import datetime
    for week in range(1, last_week + 1):
        date = ("2026-09-13" if date is None
                else (datetime.date.fromisoformat(date)
                      + datetime.timedelta(days=7)).isoformat())
        if week == bye_week:
            continue
        games.append({
            "index": index, "nfl_week": week, "label": "vs. Team",
            "result": engine.UNPLAYED, "weight": 0.5, "points_for": None,
            "points_against": None, "division": False, "date": date,
        })
        index += 1
    mapping = {str(g["nfl_week"]): g["index"] for g in games}
    mapping[str(bye_week)] = None
    return {
        "year": 2026, "games": games, "bye_week": bye_week,
        "bye_weeks": [bye_week], "week_to_game_index": mapping,
        "sheet": dict(season_mod.DEFAULT_SHEET), "snapshots": [],
    }


class TestByeWeekResolution(unittest.TestCase):
    """The week the run records comes from the calendar, not the scoreboard."""

    def test_the_bye_week_has_a_date_of_its_own(self):
        # It has no game, so nothing dates it but the week before it.
        dates = season_mod.week_dates(bye_season())
        self.assertIn(10, dates)
        self.assertEqual(dates[10], "2026-11-15")
        self.assertEqual(dates[9], "2026-11-08")

    def test_the_bye_is_the_week_to_run_during_the_bye(self):
        # The reproduction: week 9 is played, week 10 never can be, and the
        # scoreboard therefore stays on 9 for a fortnight.
        season = bye_season()
        for game in season["games"]:
            if game["nfl_week"] <= 9:
                game["result"] = engine.WIN
        self.assertEqual(season_mod.current_nfl_week(season), 9)
        self.assertEqual(season_mod.week_to_run(season, "2026-11-17"), 10)

    def test_the_week_before_the_bye_is_still_the_week_before_the_bye(self):
        season = bye_season()
        self.assertEqual(season_mod.week_to_run(season, "2026-11-10"), 9)

    def test_the_week_after_the_bye_moves_on(self):
        season = bye_season()
        self.assertEqual(season_mod.week_to_run(season, "2026-11-22"), 11)

    def test_before_the_season_it_is_the_preseason_board(self):
        season = bye_season()
        self.assertEqual(season_mod.week_to_run(season, "2026-08-01"), 0)

    def test_after_the_finale_it_clamps_to_the_last_week(self):
        season = bye_season()
        self.assertEqual(season_mod.week_to_run(season, "2027-06-01"), 18)

    def test_the_real_2026_schedule_lands_on_its_bye(self):
        # The one that matters. Not a constructed fixture: the season file the
        # pool will actually run against.
        season = season_mod.load(2026)
        self.assertTrue(season_mod.is_bye_week(season, 10))
        self.assertEqual(season_mod.week_to_run(season, "2026-11-17"), 10)


# ---------------------------------------------------------------------------
# September 2026, finding 3: weekly snapshots and chart files were overwriteable
# ---------------------------------------------------------------------------

class TestSnapshotsFreeze(unittest.TestCase):
    """`CLAUDE.md` promises a week's row is identical in week N+1. Now it is."""

    def setUp(self):
        self.season = season_mod.load(2026)
        self.board = season_mod.run(self.season, through_week=0)

    def test_a_first_recording_is_created(self):
        season = dict(self.season, snapshots=[])
        _, status = season_mod.snapshot(season, 0, self.board)
        self.assertEqual(status, "created")

    def test_an_identical_replay_writes_nothing(self):
        entry, status = season_mod.snapshot(self.season, 0, self.board)
        self.assertEqual(status, "unchanged")
        # The stored entry comes back, not a fresh one. This is what stopped
        # the run producing a commit that only moved a timestamp.
        self.assertIs(entry, season_mod.get_snapshot(self.season, 0))

    def test_a_replay_does_not_move_the_timestamp(self):
        before = season_mod.get_snapshot(self.season, 0)["taken_at"]
        season_mod.snapshot(self.season, 0, self.board)
        self.assertEqual(season_mod.get_snapshot(self.season, 0)["taken_at"],
                         before)

    def test_one_moved_weight_is_refused_by_name(self):
        # Codex's reproduction, exactly: change a single FUTURE weight, re-run
        # week 0, and every stored probability moves.
        self.season["games"][14]["weight"] = 0.99
        board = season_mod.run(self.season, through_week=0)
        with self.assertRaises(engine.SeasonError) as caught:
            season_mod.snapshot(self.season, 0, board)
        message = str(caught.exception)
        self.assertIn("week 0 is already recorded", message)
        self.assertIn("weighted.", message)      # names what moved
        self.assertIn("--correction", message)   # and how to mean it

    def test_a_refused_replay_leaves_the_stored_week_alone(self):
        before = copy.deepcopy(season_mod.get_snapshot(self.season, 0))
        self.season["games"][14]["weight"] = 0.99
        board = season_mod.run(self.season, through_week=0)
        with self.assertRaises(engine.SeasonError):
            season_mod.snapshot(self.season, 0, board)
        self.assertEqual(season_mod.get_snapshot(self.season, 0), before)

    def test_a_declared_correction_is_written_and_recorded(self):
        self.season["games"][14]["weight"] = 0.99
        board = season_mod.run(self.season, through_week=0)
        entry, status = season_mod.snapshot(self.season, 0, board,
                                            correction="ESPN moved the line")
        self.assertEqual(status, "corrected")
        self.assertEqual(len(entry["corrections"]), 1)
        self.assertEqual(entry["corrections"][0]["reason"], "ESPN moved the line")
        # A correction that leaves no trace is drift with better manners.
        self.assertTrue(entry["corrections"][0]["changed"])
        self.assertTrue(entry["corrections"][0]["at"])

    def test_corrections_accumulate_rather_than_replace(self):
        for weight, reason in ((0.99, "first"), (0.11, "second")):
            self.season["games"][14]["weight"] = weight
            board = season_mod.run(self.season, through_week=0)
            entry, _ = season_mod.snapshot(self.season, 0, board,
                                           correction=reason)
        self.assertEqual([c["reason"] for c in entry["corrections"]],
                         ["first", "second"])

    def test_the_note_is_not_part_of_the_record(self):
        # Two runs that saw the same season are the same recording, whatever
        # was written beside them.
        _, status = season_mod.snapshot(self.season, 0, self.board,
                                        note="a different note")
        self.assertEqual(status, "unchanged")

    def test_drift_is_reported_in_the_shape_code_gs_uses(self):
        stored = {"weighted": {"Amir": 12.3}, "weights": [0.55]}
        incoming = {"weighted": {"Amir": 11.8}, "weights": [0.61]}
        self.assertEqual(season_mod.snapshot_drift(stored, incoming),
                         ["weighted.Amir: 12.3 -> 11.8", "weights[0]: 0.55 -> 0.61"])


class TestANoOpRunLeavesNoTrace(unittest.TestCase):
    """The six empty "weekly run" commits in this repo's history.

    Freezing the snapshot was not enough on its own: the season file rewrote
    `updated_at` and `last_refresh` regardless, and the backup stages the whole
    `data` directory, so a run that changed nothing still produced a commit
    claiming it had.
    """

    def setUp(self):
        # Read the real season first, then point saves at scratch. The other
        # order would have `load` looking in an empty directory.
        self.season = season_mod.load(2026)
        self.dir = tempfile.mkdtemp()
        self.original = season_mod.DATA_DIR
        season_mod.DATA_DIR = self.dir

    def tearDown(self):
        season_mod.DATA_DIR = self.original
        shutil.rmtree(self.dir, ignore_errors=True)

    def _save(self, season):
        path = season_mod.save(season)
        return path, os.stat(path).st_mtime_ns

    def test_saving_an_unchanged_season_does_not_touch_the_file(self):
        season = self.season
        path, before = self._save(season)
        time.sleep(0.01)
        season["last_refresh"] = "2099-01-01T00:00:00"   # asked again, learned nothing
        self.assertEqual(self._save(season)[1], before)

    def test_a_real_change_is_still_written(self):
        season = self.season
        path, before = self._save(season)
        time.sleep(0.01)
        season["games"][3]["weight"] = 0.123456
        self.assertNotEqual(self._save(season)[1], before)

    def test_a_real_change_moves_the_updated_stamp(self):
        season = self.season
        self._save(season)
        stamped = season["updated_at"]
        season["games"][3]["weight"] = 0.123456
        season["updated_at"] = "not a time"
        self._save(season)
        self.assertNotEqual(season["updated_at"], "not a time")
        self.assertTrue(season["updated_at"] >= stamped)


class TestPublishedWeeksFreeze(unittest.TestCase):
    """A chart URL a newsletter has already sent out is a promise."""

    def setUp(self):
        self.season = season_mod.load(2026)
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _publish(self, **kwargs):
        return publish.publish_from_season(self.season, week=0,
                                           out_dir=self.dir, **kwargs)[0]

    def test_republishing_the_same_week_touches_nothing(self):
        path = self._publish()
        before = os.stat(path).st_mtime_ns
        time.sleep(0.01)
        self.assertEqual(self._publish(), path)
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_a_changed_week_is_refused(self):
        self._publish()
        self.season["snapshots"][0]["weighted"]["Amir"] = 99.9
        with self.assertRaises(publish.PublishedWeekError):
            self._publish()

    def test_a_declared_correction_goes_through(self):
        path = self._publish()
        self.season["snapshots"][0]["weighted"]["Amir"] = 99.9
        self._publish(correction="ESPN corrected the score")
        self.assertIn("99.9", open(path).read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
