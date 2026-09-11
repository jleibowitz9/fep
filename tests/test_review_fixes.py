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

September 2026, second review:

  TestScheduleIdentity       a game was identified by its position in ESPN's
                             payload, so a reordered pull rescored every pick
                             against a different game and raised nothing
  TestStaleESPNIsReported    a refresh during an ESPN outage was word for word
                             a refresh that found nothing new
  TestEliminationIsAboutRules  the snapshot and the CMS each called a live
                             competitor mathematically out, one from the
                             rounded board and one from the weighted one
  TestUnplayedWeekIsNotFrozen  the calendar stepped onto a week at midnight,
                             so a Sunday-morning run froze a pre-game board
  TestServerAnswersOnlyItself  the control room served the page, and its
                             token, to any Host that reached it
  TestHeatCheckNamesItsBaseline  the standings "Chg" column implied last week
                             even when the last snapshot was older

September 2026, round two:

  TestOverrideHasAPath       set_override had no caller: the only way to pin
                             a result was to edit the season file by hand
  TestAliveIsOneFact         the CMS, the terminal and the stat pack each
                             counted "still alive" a different way
  TestDashboardShowsRecordedWeek  the page chose its week off the scoreboard
                             and dropped the bye week's snapshot
  TestDecidingLayerIsPublished  the Decision Tree's Auto source read a key
                             the publish step never wrote
  TestControlRoomFollowUps   three refusals told you to retype a command with
                             a flag; the page now offers the button
"""

from __future__ import annotations

import contextlib
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

DASHBOARD = os.path.join(ROOT, "dashboard")

from fep import (analytics, chart, cms, engine, espn, publish,  # noqa: E402
                 season as season_mod)


@contextlib.contextmanager
def _espn_returning(pulled):
    """Make season_mod.refresh see a specific ESPN pull."""
    original = season_mod.espn.fetch_season
    season_mod.espn.fetch_season = lambda year, refresh=True: pulled
    try:
        yield
    finally:
        season_mod.espn.fetch_season = original


@contextlib.contextmanager
def _espn_offline():
    """Every request fails, so _get falls back to whatever is cached."""
    import urllib.error
    import urllib.request
    original = urllib.request.urlopen

    def refuse(*args, **kwargs):
        raise urllib.error.URLError("offline, for the test")

    urllib.request.urlopen = refuse
    try:
        yield
    finally:
        urllib.request.urlopen = original


def _load_serve():
    """dashboard/serve.py, loaded by path because the name is too generic."""
    sys.path.insert(0, DASHBOARD)
    spec = importlib.util.spec_from_file_location(
        "fep_serve_review", os.path.join(DASHBOARD, "serve.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



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
        # Take the stored week 0 from exactly the state these tests replay.
        #
        # Reading the live file's own snapshot instead made these fail the
        # moment ESPN moved a line, because the board then genuinely differs
        # from what was recorded -- which is the thing being tested, not a
        # thing to test against. Same dependency on live data that made the
        # dashboard fixture unreproducible; see tests/test_fixture.py.
        self.season = season_mod.load(2026)
        self.season["snapshots"] = []
        self.board = season_mod.run(self.season, through_week=0)
        season_mod.snapshot(self.season, 0, self.board)

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
        # A distinctive value, so this cannot pass merely because both
        # recordings landed inside the same second.
        season_mod.get_snapshot(self.season, 0)["taken_at"] = "2026-09-09T22:00:53"
        season_mod.snapshot(self.season, 0, self.board)
        self.assertEqual(season_mod.get_snapshot(self.season, 0)["taken_at"],
                         "2026-09-09T22:00:53")

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


# ---------------------------------------------------------------------------
# September 2026, second review
# ---------------------------------------------------------------------------


class TestScheduleIdentity(unittest.TestCase):
    """A game is its ESPN event id, never its position in the payload.

    `index` is the position in the 17-entry pick array, so it is what every
    pick, result and division index hangs off. It used to be assigned in
    whatever order ESPN serialised its events, and `refresh` then matched
    stored to fresh on it and overwrote `event_id` from whatever landed there.
    A reordered pull therefore rescored the whole season against other games
    and raised nothing.
    """

    def _payload(self):
        path = os.path.join(ROOT, "data", "espn_cache", "schedule_2026.json")
        with open(path) as fh:
            return json.load(fh)

    def test_a_shuffled_payload_still_parses_in_schedule_order(self):
        payload = self._payload()
        payload["events"].reverse()
        weeks = [g["nfl_week"] for g in espn.parse_schedule(payload, 2026)]
        self.assertEqual(weeks, sorted(weeks))

    def test_a_shuffled_payload_does_not_move_the_division_games(self):
        straight = espn.division_indices(espn.parse_schedule(self._payload(), 2026))
        payload = self._payload()
        payload["events"][0], payload["events"][3] = (
            payload["events"][3], payload["events"][0])
        self.assertEqual(
            espn.division_indices(espn.parse_schedule(payload, 2026)), straight)

    def test_a_missing_week_number_does_not_throw(self):
        payload = self._payload()
        payload["events"][2].pop("week", None)
        self.assertEqual(len(espn.parse_schedule(payload, 2026)), 17)

    def test_a_pull_with_a_different_game_is_refused(self):
        season = season_mod.load(2026)
        pulled = copy.deepcopy(espn.fetch_season(2026, refresh=False))
        pulled["games"][0]["event_id"] = "999999999"
        with _espn_returning(pulled):
            with self.assertRaises(engine.SeasonError) as caught:
                season_mod.refresh(copy.deepcopy(season))
        self.assertIn("999999999", str(caught.exception))

    def test_a_reordered_pull_does_not_move_the_stored_games(self):
        season = season_mod.load(2026)
        pulled = copy.deepcopy(espn.fetch_season(2026, refresh=False))
        # Same games, re-indexed backwards: the shape the old code accepted.
        pulled["games"].reverse()
        for position, game in enumerate(pulled["games"]):
            game["index"] = position
        with _espn_returning(pulled):
            refreshed = season_mod.refresh(copy.deepcopy(season))
        self.assertEqual([g["event_id"] for g in refreshed["games"]],
                         [g["event_id"] for g in season["games"]])
        self.assertEqual([g["opponent"] for g in refreshed["games"]],
                         [g["opponent"] for g in season["games"]])


class TestStaleESPNIsReported(unittest.TestCase):
    """An outage and a quiet week used to print the same three lines.

    Falling back to the cache is the feature that makes this work offline. Not
    saying so is what let a board built on last week's weights freeze into a
    snapshot wearing this week's date.
    """

    def test_a_failed_fetch_is_named_in_the_changes(self):
        season = season_mod.load(2026)
        with _espn_offline():
            refreshed = season_mod.refresh(copy.deepcopy(season), force=True)
        changes = refreshed["last_refresh_changes"]
        self.assertTrue(any("did not answer" in c for c in changes), changes)

    def test_a_healthy_fetch_reports_nothing_of_the_kind(self):
        season = season_mod.load(2026)
        refreshed = season_mod.refresh(copy.deepcopy(season), force=False)
        self.assertFalse(
            any("did not answer" in c for c in refreshed["last_refresh_changes"]))

    def test_the_stale_list_does_not_carry_over_between_pulls(self):
        with _espn_offline():
            espn.fetch_season(2026, refresh=True)
        self.assertEqual(espn.fetch_season(2026, refresh=False)["stale"], [])


class TestEliminationIsAboutRules(unittest.TestCase):
    """Mathematically out means no winning outcome, not long odds.

    Three separate readings of this existed: the engine's (right), the
    snapshot's (weighted == 0) and the CMS standings table's (the board rounded
    to one decimal). The last two could each bury somebody who was still alive,
    and could contradict competitors.eliminated_week in the same push.
    """

    # Two games won, three to go, each a 99% favourite. "Longshot" wins
    # outright in exactly one of the eight outcomes, which is 0.0001% of the
    # probability and 12.5% of the outcomes.
    RESULTS = ["W", "W", "A", "A", "A"]
    WEIGHTS = [None, None, 0.99, 0.99, 0.99]
    SCORED = [24, 24, None, None, None]

    def _board(self):
        return engine.run(
            {"Leader": ["W", "W", "W", "W", "W"],
             "Second": ["W", "W", "W", "W", "W"],
             "Longshot": ["L", "L", "L", "L", "L"]},
            self.RESULTS, self.WEIGHTS, [0],
            {"Leader": 400.0, "Second": 500.0, "Longshot": 420.0},
            points_scored=self.SCORED)

    def test_a_longshot_wins_outcomes_and_is_not_eliminated(self):
        board = self._board()
        self.assertGreater(board.straight["Longshot"], 0.0)
        self.assertLess(round(board.weighted["Longshot"], 1), 0.05)
        self.assertNotIn("Longshot", board.eliminated())

    def test_the_snapshot_records_the_engines_answer(self):
        season = copy.deepcopy(season_mod.load(2026))
        board = season_mod.run(season)
        entry, _ = season_mod.snapshot(season, 0, board, correction="test")
        self.assertEqual(entry["eliminated"], sorted(board.eliminated()))

    def test_the_cms_does_not_read_elimination_off_the_rounded_board(self):
        board = self._board()
        season = {"year": 2099, "games": [], "week_to_game_index": {},
                  "snapshots": [{
                      "week": 1,
                      "weighted": {n: round(board.weighted[n], 1) for n in board.order},
                      "eliminated": sorted(board.eliminated()),
                      "straight": {}, "current_points": {}}]}
        rows = {r["name"]: r for r in cms.standings_table(season).rows}
        self.assertEqual(rows["Longshot"]["weighted"], 0.0)
        self.assertFalse(rows["Longshot"]["is_eliminated"])

    def test_the_two_cms_tables_cannot_disagree(self):
        board = self._board()
        season = {"year": 2099, "games": [], "week_to_game_index": {},
                  "snapshots": [{
                      "week": 1,
                      "weighted": {n: round(board.weighted[n], 1) for n in board.order},
                      "eliminated": sorted(board.eliminated()),
                      "straight": {}, "current_points": {}}]}
        rows = {r["name"]: r for r in cms.standings_table(season).rows}
        for name in board.order:
            self.assertEqual(rows[name]["is_eliminated"],
                             cms.eliminated_week(season, name) is not None,
                             "{} is described two ways".format(name))

    def test_a_tie_at_the_points_tiebreaker_is_still_a_live_path(self):
        # Identical pick sheets: tied in every universe, separated only by the
        # points guess. The model gives 500 no mass, but the rulebook does not
        # know the final total, so this is not elimination.
        board = engine.run(
            {"Leader": ["W", "W", "W", "W", "W"],
             "Second": ["W", "W", "W", "W", "W"],
             "Other": ["L", "W", "W", "W", "W"]},
            self.RESULTS, [None, None, 0.5, 0.5, 0.5], [0],
            {"Leader": 400.0, "Second": 500.0, "Other": 420.0},
            points_scored=self.SCORED)
        self.assertEqual(board.straight["Second"], 0.0)
        self.assertNotIn("Second", board.eliminated())
        self.assertIn("Other", board.eliminated())

    def test_every_real_snapshot_agrees_with_both_readings(self):
        # The fix must not move a single row that has already been published.
        for year in (2025, 2026):
            season = season_mod.load(year)
            for snapshot in season.get("snapshots") or []:
                rounded = sorted(n for n, v in snapshot["weighted"].items() if v == 0)
                self.assertEqual(sorted(snapshot.get("eliminated") or []), rounded,
                                 "{} week {}".format(year, snapshot["week"]))


class TestUnplayedWeekIsNotFrozen(unittest.TestCase):
    """The calendar steps onto a week at midnight; kickoff is hours later.

    A snapshot freezes, so a Sunday-morning run pinned a pre-game board as the
    week and the real run that evening needed --correction "why" -- an audit
    entry for an early click rather than a genuine correction.
    """

    def _cli(self):
        spec = importlib.util.spec_from_file_location(
            "fep_cli", os.path.join(ROOT, "cli.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_default_run_refuses_a_week_that_has_not_happened(self):
        cli = self._cli()
        original = season_mod.week_to_run
        season_mod.week_to_run = lambda season, today=None: 1
        try:
            with self.assertRaises(SystemExit) as caught:
                cli.COMMANDS["week"]([])
        finally:
            season_mod.week_to_run = original
        self.assertIn("has not been played yet", str(caught.exception))

    def test_a_bye_week_is_not_caught_by_the_guard(self):
        season = season_mod.load(2026)
        for week in (0, season["bye_week"]):
            self.assertIsNone(season_mod.game_index_for_week(season, week))


class TestServerAnswersOnlyItself(unittest.TestCase):
    """GET / renders the action token into the page, so the Host matters.

    A name that resolves to 127.0.0.1 is same-origin with this server as far as
    the browser is concerned. Binding to loopback stops the network; this stops
    the name.
    """

    def _handler(self, host):
        serve = _load_serve()
        handler = serve.Handler.__new__(serve.Handler)
        handler.headers = {"Host": host}
        return handler

    def test_loopback_is_accepted(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765", "127.0.0.1"):
            self.assertTrue(self._handler(host)._local_host(), host)

    def test_any_other_name_is_refused(self):
        for host in ("evil.example.com:8765", "fep.attacker.test", "192.168.1.9:8765"):
            self.assertFalse(self._handler(host)._local_host(), host)


class TestHeatCheckNamesItsBaseline(unittest.TestCase):
    """standings_table refuses a change across a gap; this segment labels it.

    Printing a two-week move under a column headed "Chg" reads as one week.
    """

    def test_a_consecutive_baseline_is_marked_as_such(self):
        season = copy.deepcopy(season_mod.load(2025))
        board = season_mod.run(season, through_week=5)
        heat = analytics.heat_check(season, board, 5)
        self.assertEqual(heat["baseline_week"], 4)
        self.assertTrue(heat["baseline_is_previous_week"])

    def test_a_gap_is_marked_as_a_gap(self):
        season = copy.deepcopy(season_mod.load(2025))
        season["snapshots"] = [s for s in season["snapshots"] if s["week"] != 4]
        board = season_mod.run(season, through_week=5)
        heat = analytics.heat_check(season, board, 5)
        self.assertEqual(heat["baseline_week"], 3)
        self.assertFalse(heat["baseline_is_previous_week"])


# ---------------------------------------------------------------------------
# September 2026, round two
# ---------------------------------------------------------------------------


def _longshot_board():
    """Two games won, three 99% favourites to go. Longshot wins one outcome
    in eight; Second ties Leader everywhere and is separated by the points."""
    return engine.run(
        {"Leader": ["W"] * 5, "Second": ["W"] * 5, "Longshot": ["L"] * 5},
        ["W", "W", "A", "A", "A"], [None, None, 0.99, 0.99, 0.99], [0],
        {"Leader": 400.0, "Second": 500.0, "Longshot": 420.0},
        points_scored=[24, 24, None, None, None])


def _snapshot_of(board, week=1, results=None):
    return {"week": week,
            "weighted": {n: round(board.weighted[n], 1) for n in board.order},
            "straight": {n: round(board.straight[n], 1) for n in board.order},
            "eliminated": sorted(board.eliminated()),
            "current_points": dict(board.current_points),
            "deciding": {k: round(v, 1) for k, v in board.deciding.items()},
            "remaining_outcomes": board.remaining_outcomes,
            "results": results or ["W", "W", "A", "A", "A"]}


class _TempSeason(unittest.TestCase):
    """Point the season module at a scratch copy of the 2026 file."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        shutil.copy(season_mod.path_for(2026), self.dir)
        self._data_dir = season_mod.DATA_DIR
        season_mod.DATA_DIR = self.dir

    def tearDown(self):
        season_mod.DATA_DIR = self._data_dir
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cli(self):
        spec = importlib.util.spec_from_file_location(
            "fep_cli_override", os.path.join(ROOT, "cli.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _game(self, index):
        return next(g for g in season_mod.load(2026)["games"] if g["index"] == index)


class TestOverrideHasAPath(_TempSeason):
    """`cli.py override` is the command the runbook always described."""

    def test_a_result_can_be_pinned_and_survives_refresh(self):
        cli = self._cli()
        cli.COMMANDS["override"](["3", "result", "L"])
        game = self._game(3)
        self.assertEqual(game["result"], "L")
        self.assertEqual(game["result_source"], "manual")
        season = season_mod.load(2026)
        with _espn_returning(espn.fetch_season(2026, refresh=False)):
            season_mod.refresh(season)
        self.assertEqual(next(g for g in season["games"] if g["index"] == 3)["result"], "L")

    def test_a_weight_accepts_a_percent(self):
        cli = self._cli()
        cli.COMMANDS["override"](["w5", "weight", "62%"])
        game = next(g for g in season_mod.load(2026)["games"] if g["nfl_week"] == 5)
        self.assertEqual(game["weight"], 0.62)
        self.assertEqual(game["weight_source"], "manual")

    def test_clear_hands_the_field_back_to_espn(self):
        cli = self._cli()
        cli.COMMANDS["override"](["3", "weight", "0.9"])
        cli.COMMANDS["override"](["3", "weight", "--clear"])
        game = self._game(3)
        self.assertEqual(game["weight_source"], "espn")
        self.assertNotEqual(game["weight"], 0.9)

    def test_nonsense_is_refused_in_a_sentence(self):
        cli = self._cli()
        for argv in (["3", "weight", "1.5"], ["3", "result", "X"], ["3", "points", "-4"],
                     ["w10", "result", "W"], ["99", "result", "W"], ["3", "colour", "red"]):
            with self.assertRaises(SystemExit, msg=argv):
                cli.COMMANDS["override"](argv)
        self.assertEqual(self._game(3)["result_source"], "espn")

    def test_clearing_a_result_cannot_orphan_a_pinned_score(self):
        cli = self._cli()
        cli.COMMANDS["override"](["3", "result", "W"])
        cli.COMMANDS["override"](["3", "points", "27"])
        with self.assertRaises(SystemExit) as caught:
            cli.COMMANDS["override"](["3", "result", "--clear"])
        self.assertIn("Clear the points", str(caught.exception))
        game = self._game(3)
        self.assertEqual((game["result"], game["result_source"]), ("W", "manual"))
        cli.COMMANDS["override"](["3", "points", "--clear"])
        cli.COMMANDS["override"](["3", "result", "--clear"])
        game = self._game(3)
        self.assertEqual((game["result"], game["points_for"]), (engine.UNPLAYED, None))

    def test_a_bare_decimal_above_one_is_refused_not_guessed(self):
        cli = self._cli()
        with self.assertRaises(SystemExit) as caught:
            cli.COMMANDS["override"](["3", "weight", "1.5"])
        self.assertIn("say which you meant", str(caught.exception))
        cli.COMMANDS["override"](["3", "weight", "62"])
        self.assertEqual(self._game(3)["weight"], 0.62)

    def test_a_score_on_an_unplayed_game_is_refused_by_the_engine(self):
        cli = self._cli()
        with self.assertRaises(engine.SeasonError):
            cli.COMMANDS["override"](["3", "points", "24"])


class TestAliveIsOneFact(unittest.TestCase):
    """The surfaces that say "alive" all read the rules."""

    def test_the_weeks_table_reads_the_structural_field(self):
        board = _longshot_board()
        season = {"year": 2099, "games": [], "week_to_game_index": {},
                  "bye_weeks": [], "bye_week": None,
                  "snapshots": [_snapshot_of(board)]}
        row = cms.weeks_table(season).rows[0]
        self.assertEqual(row["still_alive"], len(board.order) - len(board.eliminated()))
        self.assertEqual(row["still_alive"], 3)

    def test_the_stat_pack_and_the_run_agree_with_the_engine(self):
        from fep import statpack
        season = copy.deepcopy(season_mod.load(2026))
        board = season_mod.run(season, through_week=0)
        pack = analytics.full_pack(season, board, 0, through_week=0)
        path = os.path.join(tempfile.mkdtemp(), "statpack.md")
        statpack.write(season, board, 0, path, pack)
        text = open(path).read()
        alive = len(pack["elimination"]["alive"])
        self.assertIn("{} still alive".format(alive), text)
        self.assertIn("{} with a live path".format(alive), text)


class TestDashboardShowsRecordedWeek(unittest.TestCase):
    """collect() defaults to the last snapshot, which is what was published."""

    def _collect_with(self, season):
        spec = importlib.util.spec_from_file_location(
            "dashboard_build_r2", os.path.join(DASHBOARD, "build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        original = season_mod.load
        season_mod.load = lambda year: copy.deepcopy(season)
        try:
            return build.collect(season["year"])
        finally:
            season_mod.load = original

    def test_a_bye_week_snapshot_is_the_week_shown(self):
        # Sit the season inside its bye: every game before it played, the bye
        # itself snapshotted, nothing after. The scoreboard says the week
        # before; the record says the bye.
        season = copy.deepcopy(season_mod.load(2025))
        bye = season["bye_week"]
        season["snapshots"] = [s for s in season["snapshots"] if s["week"] <= bye]
        for game in season["games"]:
            if game["nfl_week"] > bye:
                game["result"], game["points_for"] = engine.UNPLAYED, None
        self.assertEqual(season_mod.current_nfl_week(season), bye - 1)
        data = self._collect_with(season)
        self.assertEqual(data["week"], bye)
        self.assertIn(bye, [s["week"] for s in data["snapshots"]])

    def test_no_snapshots_falls_back_to_the_scoreboard(self):
        season = copy.deepcopy(season_mod.load(2025))
        season["snapshots"] = []
        for game in season["games"]:
            if game["nfl_week"] > 3:
                game["result"], game["points_for"] = engine.UNPLAYED, None
        self.assertEqual(self._collect_with(season)["week"], 3)


class TestDecidingLayerIsPublished(unittest.TestCase):
    """week-NN.json carries the Decision Tree the component's Auto source reads."""

    def test_the_payload_has_rows_outcomes_and_a_baseline(self):
        board = _longshot_board()
        deciding = {0: {"outright": 60.0, "tb1": 30.0, "tb2": 10.0, "tb3": 0.0, "split": 0.0},
                    1: {k: round(v, 1) for k, v in board.deciding.items()}}
        payload = chart.build_payload(
            [0, 1], {0: {n: 33.3 for n in board.order},
                     1: {n: round(board.weighted[n], 1) for n in board.order}},
            board.order, deciding=deciding, outcomes={0: 32, 1: 8}, upto_week=1)
        layer = payload["deciding"]
        self.assertEqual(layer["outcomes"], 8)
        self.assertEqual(layer["baseline_week"], 0)
        rows = {r["key"]: r for r in layer["rows"]}
        self.assertEqual(rows["outright"]["delta"],
                         round(rows["outright"]["share"] - 60.0, 1))
        self.assertNotIn("split", rows)          # zero, so omitted
        self.assertEqual([r["key"] for r in layer["rows"]][:1], ["outright"])

    def test_the_first_week_has_no_delta_and_no_baseline(self):
        board = _longshot_board()
        payload = chart.build_payload(
            [0], {0: {n: 33.3 for n in board.order}}, board.order,
            deciding={0: {k: round(v, 1) for k, v in board.deciding.items()}},
            outcomes={0: 8})
        self.assertIsNone(payload["deciding"]["baseline_week"])
        self.assertTrue(all(r["delta"] is None for r in payload["deciding"]["rows"]))

    def test_a_payload_without_it_says_so_rather_than_guessing(self):
        board = _longshot_board()
        payload = chart.build_payload([0], {0: {n: 33.3 for n in board.order}}, board.order)
        self.assertIsNone(payload["deciding"])

    def test_the_stat_pack_and_the_published_file_share_one_shape(self):
        season = copy.deepcopy(season_mod.load(2025))
        board = season_mod.run(season, through_week=10)
        pack_rows = analytics.deciding_layer(season, board, 10)["rows"]
        out = tempfile.mkdtemp()
        paths = publish.publish_from_season(season, out_dir=out)
        with open(next(p for p in paths if p.endswith("week-10.json"))) as fh:
            file_rows = json.load(fh)["deciding"]["rows"]
        self.assertEqual([sorted(r) for r in pack_rows], [sorted(r) for r in file_rows])
        self.assertEqual([r["key"] for r in pack_rows], [r["key"] for r in file_rows])

    def test_every_published_file_carries_it(self):
        for year in (2025, 2026):
            folder = os.path.join(ROOT, "chart-data", str(year))
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name)) as fh:
                    payload = json.load(fh)
                self.assertIsNotNone(payload.get("deciding"), "{}/{}".format(year, name))
                self.assertTrue(payload["deciding"]["rows"], "{}/{}".format(year, name))


class TestControlRoomFollowUps(unittest.TestCase):
    """The page offers the flag a refusal asked for; the server passes it on."""

    @classmethod
    def setUpClass(cls):
        cls.serve = _load_serve()
        cls.cli = cls.serve.cli
        with open(os.path.join(DASHBOARD, "template.html")) as fh:
            cls.template = fh.read()

    def _capture_argv(self, command, payload_fn):
        seen = []

        def fake(argv):
            seen.append(list(argv))
            raise SystemExit("stopped by the test")
        original = self.cli.COMMANDS[command]
        self.cli.COMMANDS[command] = fake
        try:
            payload_fn()
        finally:
            self.cli.COMMANDS[command] = original
        return seen

    def test_a_correction_reaches_the_weekly_run(self):
        seen = self._capture_argv(
            "week", lambda: self.serve._week({"week": "3", "correction": "ESPN fixed it"}))
        self.assertEqual(seen, [["3", "--correction", "ESPN fixed it"]])

    def test_a_blank_correction_is_not_passed(self):
        seen = self._capture_argv("week", lambda: self.serve._week({"week": "3", "correction": "  "}))
        self.assertEqual(seen, [["3"]])

    def test_allow_correction_reaches_the_cms_push(self):
        fn = self.serve.ACTIONS["cms-live"][1]
        self.assertEqual(self._capture_argv("cms", lambda: fn({"allow_correction": True})),
                         [["--live", "--allow-correction"]])
        self.assertEqual(self._capture_argv("cms", lambda: fn({})), [["--live"]])

    def test_an_override_is_one_cli_call_per_field(self):
        fn = self.serve.ACTIONS["override"][1]
        seen = self._capture_argv(
            "override", lambda: fn({"index": 3, "fields": {"result": "L", "weight": "62", "points": ""}}))
        # Points first, then weight, then result (so a clear never orphans a
        # score); a blank field is skipped; it stops at the first failure,
        # which the fake supplies on the first call.
        self.assertEqual(seen, [["3", "weight", "62"]])

    def test_clearing_nothing_is_refused_before_any_call(self):
        fn = self.serve.ACTIONS["override"][1]
        result = fn({"index": 3, "clear": True})
        self.assertFalse(result["ok"])
        self.assertIn("Nothing is overridden", result["error"])
        self.assertIn("override", self.serve.REWARM)

    def test_the_page_carries_the_controls(self):
        for needle in ('data-follow="week-correction"', 'data-follow="override"',
                       'data-follow="override-clear"', "JSON.parse(b.dataset.extra)",
                       'id="ctlFollow"', "pointsSource", "override:1"):
            self.assertIn(needle, self.template, needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
