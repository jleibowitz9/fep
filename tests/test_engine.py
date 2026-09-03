"""
Tests for the FEP engine.

Run:  python3 tests/test_engine.py

The important ones:

  test_reproduces_2025          the new engine must match Jacob's published
                                boards exactly, or the family's history changes
  test_tied_points_guesses_*    the bug that was latent in 2025
  test_sheet_range_guard        the Sheet writer must never be able to touch
                                column A or the placement formulas
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fep import chart, engine, sheets, statpack  # noqa: E402

SKILL = os.path.expanduser(
    "~/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/"
    "d1014f01-77c2-4a2b-bb91-a8c459904777/a772b5d9-f193-460e-9d65-086a1d1f8efc/"
    "skills/fep-master"
)
OLD_SIM = os.path.join(ROOT, "..", "2025", "simulator.py")

SCORES_2025 = [24, 20, 33, 31, 17, 17, 28, 38, 10, 16, 21, 15, 19, 31, 29, 13, 17]


def load_2025():
    spec = importlib.util.spec_from_file_location("old2025", OLD_SIM)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------


class TestRegression(unittest.TestCase):
    """The new engine must not change what the family already saw."""

    @classmethod
    def setUpClass(cls):
        cls.old = load_2025()

    def test_reproduces_2025_week_by_week(self):
        old = self.old
        picks, divisions = old.picks_dict, old.division_weeks
        guesses = old.predicted_points
        weights = [old.weight[i] for i in range(17)]
        final = old.eagles_results

        mismatches = []
        for played in range(18):
            results = final[:played] + ["A"] * (17 - played)
            remaining = 17 - played
            mean = (sum(SCORES_2025[:played]) / played * 17) if played else 23.0 * 17
            sd = max(1.0, 11.0 * (remaining ** 0.5))

            board = engine.run(picks, results, weights, divisions, guesses,
                               points_mean=mean, points_sd=sd)
            legacy = old.run_simulation(
                results, {i: weights[i] for i in range(17)},
                picks, divisions, guesses, mean)
            legacy_board = dict(zip(picks.keys(), legacy["weighted"]))

            for name in picks:
                if round(board.weighted[name], 1) != legacy_board[name]:
                    mismatches.append(
                        (played, name, round(board.weighted[name], 1), legacy_board[name]))

        self.assertEqual(mismatches, [], "engine disagrees with the 2025 simulator")

    def test_2025_final_board_crowns_pop(self):
        old = self.old
        board = engine.run(old.picks_dict, old.eagles_results,
                           [old.weight[i] for i in range(17)],
                           old.division_weeks, old.predicted_points,
                           points_scored=SCORES_2025)
        self.assertAlmostEqual(board.weighted["pop"], 100.0, places=6)
        self.assertEqual(board.current_points["pop"], 11)
        self.assertEqual(board.current_points["marsha"], 10)

    def test_boards_sum_to_100(self):
        old = self.old
        weights = [old.weight[i] for i in range(17)]
        for played in (0, 3, 9, 14, 17):
            results = old.eagles_results[:played] + ["A"] * (17 - played)
            board = engine.run(old.picks_dict, results, weights, old.division_weeks,
                               old.predicted_points, points_scored=SCORES_2025[:played] +
                               [None] * (17 - played))
            self.assertAlmostEqual(sum(board.weighted.values()), 100.0, places=4)
            self.assertAlmostEqual(sum(board.straight.values()), 100.0, places=4)
            self.assertAlmostEqual(sum(board.deciding.values()), 100.0, places=4)


class TestTiebreakers(unittest.TestCase):

    def test_tied_points_guesses_split_evenly(self):
        """The 2025 code split two identical guesses about 63/37."""
        shares = engine.closest_shares({"a": 400, "b": 400}, mean=390, sd=30)
        self.assertAlmostEqual(shares["a"], 0.5, places=9)
        self.assertAlmostEqual(shares["b"], 0.5, places=9)

    def test_tied_guesses_among_others_split_evenly(self):
        shares = engine.closest_shares({"a": 400, "b": 400, "c": 460}, mean=410, sd=25)
        self.assertAlmostEqual(shares["a"], shares["b"], places=9)
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)

    def test_exhausted_cascade_splits_evenly(self):
        """Identical picks AND identical points guess: nothing left to break."""
        picks = {"ann": ["W", "L", "W"], "bob": ["W", "L", "W"]}
        board = engine.run(picks, ["A"] * 3, [0.6, 0.5, 0.7], [0],
                           {"ann": 400, "bob": 400}, points_scored=[None] * 3)
        self.assertAlmostEqual(board.weighted["ann"], 50.0, places=6)
        self.assertAlmostEqual(board.weighted["bob"], 50.0, places=6)
        self.assertAlmostEqual(board.deciding["split"], 100.0, places=6)

    def test_tiebreaker_1_closest_record_wins(self):
        """Two competitors genuinely tied on correct picks, split by record.

        Weights of 1 and 0 pin the season to W, W, L, L (2 wins). Both sheets
        score exactly 2 correct, so the pick count cannot separate them, but
        "even" predicted 2 wins and "wild" predicted 4, so "even" is closer.

        Note that a tie on correct picks does NOT imply a tie on predicted wins:
        being tied fixes how many games you got wrong, not the direction you got
        them wrong in.
        """
        picks = {"even": ["W", "L", "W", "L"], "wild": ["W", "W", "W", "W"]}
        board = engine.run(picks, ["A"] * 4, [1.0, 1.0, 0.0, 0.0], [],
                           {"even": 400, "wild": 400}, points_scored=[None] * 4)
        self.assertEqual(board.current_points, {"even": 0, "wild": 0})
        self.assertAlmostEqual(board.weighted["even"], 100.0, places=4)
        self.assertAlmostEqual(board.deciding["tb1"], 100.0, places=4)

    # All-W against all-L is the clean way to reach tiebreakers 2 and 3.
    # Writing C for correct picks and P for predicted wins over a season with A
    # wins: C = a + d, P - A = b - c and b + c = n - C, where a/b/c/d count the
    # four pick-versus-result combinations. Equal C therefore forces equal
    # b + c, so to ALSO tie on |P - A| the two sheets need b and c swapped.
    # All-W and all-L do exactly that. Season pinned to W, W, L, L: both score
    # 2 correct, and both miss the 2-win record by exactly 2.
    OPTIMIST_PESSIMIST = {"optimist": ["W"] * 4, "pessimist": ["L"] * 4}
    PINNED_WWLL = [1.0, 1.0, 0.0, 0.0]

    def test_tiebreaker_2_breaks_a_tiebreaker_1_deadlock(self):
        """Tied on picks and on record, so the division record decides."""
        board = engine.run(self.OPTIMIST_PESSIMIST, ["A"] * 4, self.PINNED_WWLL,
                           [0],   # game 0 is the only division game, and it is a win
                           {"optimist": 400, "pessimist": 400}, points_scored=[None] * 4)
        self.assertAlmostEqual(board.weighted["optimist"], 100.0, places=4)
        self.assertAlmostEqual(board.deciding["tb2"], 100.0, places=4)

    def test_tiebreaker_3_breaks_a_tiebreaker_2_deadlock(self):
        """Tied on picks, record and division, so the points guess decides."""
        board = engine.run(self.OPTIMIST_PESSIMIST, ["A"] * 4, self.PINNED_WWLL,
                           [],    # no division games, so tiebreaker 2 cannot separate
                           {"optimist": 500, "pessimist": 300},
                           points_mean=310, points_sd=8)
        self.assertAlmostEqual(board.weighted["pessimist"], 100.0, places=4)
        self.assertAlmostEqual(board.deciding["tb3"], 100.0, places=4)

    def test_full_cascade_runs_in_order(self):
        """Each layer only fires once the one above it is exhausted."""
        common = dict(results=["A"] * 4, weights=self.PINNED_WWLL,
                      points_scored=[None] * 4)
        # tb1: different distance from the actual record
        tb1 = engine.run({"even": ["W", "L", "W", "L"], "wild": ["W"] * 4},
                         division_indices=[], points_guess={"even": 400, "wild": 400},
                         **common)
        self.assertAlmostEqual(tb1.deciding["tb1"], 100.0, places=4)
        # tb2: record ties, division does not
        tb2 = engine.run(self.OPTIMIST_PESSIMIST, division_indices=[0],
                         points_guess={"optimist": 400, "pessimist": 400}, **common)
        self.assertAlmostEqual(tb2.deciding["tb2"], 100.0, places=4)
        # tb3: record and division both tie
        tb3 = engine.run(self.OPTIMIST_PESSIMIST, division_indices=[],
                         points_guess={"optimist": 500, "pessimist": 300},
                         results=["A"] * 4, weights=self.PINNED_WWLL,
                         points_mean=310, points_sd=8)
        self.assertAlmostEqual(tb3.deciding["tb3"], 100.0, places=4)

    def test_tiebreaker_2_only_runs_after_tiebreaker_1(self):
        """Emer and Jen in 2025: same record, different division record.

        This is why the tied-guess bug never fired that season.
        """
        old = load_2025()
        emer, jen = old.picks_dict["emer"], old.picks_dict["jen"]
        self.assertEqual(emer.count("W"), jen.count("W"))          # tb1 cannot separate
        self.assertEqual(old.predicted_points["emer"], old.predicted_points["jen"])
        emer_div = sum(1 for i in old.division_weeks if emer[i] == "W")
        jen_div = sum(1 for i in old.division_weeks if jen[i] == "W")
        self.assertNotEqual(emer_div, jen_div)                      # tb2 always does
        # |5-a| == |6-a| has no integer solution, so tb2 separates them in every
        # possible universe, not just most of them.
        for actual in range(0, 7):
            self.assertNotEqual(abs(emer_div - actual), abs(jen_div - actual))

    def test_deciding_layer_accounts_for_everything(self):
        old = load_2025()
        board = engine.run(old.picks_dict, old.eagles_results[:9] + ["A"] * 8,
                           [old.weight[i] for i in range(17)], old.division_weeks,
                           old.predicted_points,
                           points_scored=SCORES_2025[:9] + [None] * 8)
        self.assertAlmostEqual(sum(board.deciding.values()), 100.0, places=4)
        self.assertGreater(board.deciding["outright"], 0)


class TestValidation(unittest.TestCase):

    def setUp(self):
        self.picks = {"a": ["W"] * 3, "b": ["L"] * 3}
        self.results = ["A"] * 3
        self.weights = [0.5, 0.5, 0.5]
        self.guesses = {"a": 400, "b": 400}

    def _validate(self, **overrides):
        kwargs = {"picks": self.picks, "results": self.results,
                  "weights": self.weights, "division_indices": [0],
                  "points_guess": self.guesses}
        kwargs.update(overrides)
        engine.validate(**kwargs)

    def test_short_pick_sheet_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "2 entries but the season has 3"):
            self._validate(picks={"a": ["W", "W"], "b": ["L"] * 3})

    def test_bad_pick_symbol_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "only 'W' and 'L'"):
            self._validate(picks={"a": ["W", "X", "W"], "b": ["L"] * 3})

    def test_out_of_range_weight_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "must be 0..1"):
            self._validate(weights=[0.5, 1.4, 0.5])

    def test_missing_weight_on_unplayed_game_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "no win probability"):
            self._validate(weights=[0.5, None, 0.5])

    def test_played_game_may_have_no_weight(self):
        self._validate(results=["W", "A", "A"], weights=[None, 0.5, 0.5])

    def test_out_of_range_division_index_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "outside 0..2"):
            self._validate(division_indices=[9])

    def test_missing_points_guess_is_rejected(self):
        with self.assertRaisesRegex(engine.SeasonError, "no points guess for b"):
            self._validate(points_guess={"a": 400})


class TestNonContiguousResults(unittest.TestCase):
    """Played games do not have to be a prefix. Retrospective leverage needs this."""

    def test_gap_in_results_is_handled(self):
        picks = {"a": ["W", "W", "W"], "b": ["L", "L", "L"]}
        board = engine.run(picks, ["W", "A", "W"], [1.0, 0.5, 1.0], [],
                           {"a": 400, "b": 300}, points_scored=[24, None, 30])
        self.assertEqual(board.current_points["a"], 2)
        self.assertEqual(board.current_points["b"], 0)
        self.assertEqual(board.remaining_outcomes, 2)
        self.assertAlmostEqual(board.weighted["a"], 100.0, places=6)


class TestPointsModel(unittest.TestCase):

    def test_legacy_matches_the_2025_hand_formula(self):
        results = ["W"] * 9 + ["A"] * 8
        scored = SCORES_2025[:9] + [None] * 8
        model = engine.points_distribution(results, scored, model="legacy")
        self.assertAlmostEqual(model["mean"], sum(SCORES_2025[:9]) / 9 * 17, places=6)
        self.assertAlmostEqual(model["sd"], 11.0 * (8 ** 0.5), places=6)

    def test_legacy_equals_shrunk_with_zero_prior_weight(self):
        results = ["W"] * 5 + ["A"] * 12
        scored = SCORES_2025[:5] + [None] * 12
        legacy = engine.points_distribution(results, scored, model="legacy")
        shrunk = engine.points_distribution(results, scored, prior_weight_games=0.0)
        self.assertAlmostEqual(legacy["mean"], shrunk["mean"], places=6)

    def test_shrinkage_pulls_a_one_game_sample_toward_the_prior(self):
        results = ["W"] + ["A"] * 16
        scored = [45] + [None] * 16          # one huge game
        legacy = engine.points_distribution(results, scored, model="legacy")
        shrunk = engine.points_distribution(results, scored, prior_ppg=23.0,
                                            prior_weight_games=3.0)
        self.assertGreater(legacy["mean"], shrunk["mean"])
        self.assertGreater(shrunk["sd"], 0)


class TestSheetSafety(unittest.TestCase):
    """The Sheet feeds a live public site. These are the guardrails."""

    def test_accepts_the_agreed_range(self):
        bounds = sheets.assert_safe_range("B2:M20")
        self.assertEqual((bounds["width"], bounds["height"]), (12, 19))

    def test_refuses_to_touch_column_a(self):
        with self.assertRaisesRegex(sheets.SheetError, "column A"):
            sheets.assert_safe_range("A2:M20")

    def test_refuses_to_touch_the_placement_formulas(self):
        for bad in ("B2:N20", "B2:Z20", "B2:AA20"):
            with self.assertRaisesRegex(sheets.SheetError, "placement formulas"):
                sheets.assert_safe_range(bad)

    def test_refuses_to_overwrite_the_header_row(self):
        with self.assertRaisesRegex(sheets.SheetError, "header"):
            sheets.assert_safe_range("B1:M20")

    def test_refuses_a_malformed_range(self):
        for bad in ("B2:M", "Sheet1!B2:M20", "B2", ""):
            with self.assertRaises(sheets.SheetError):
                sheets.assert_safe_range(bad)

    def test_rows_are_blank_not_zero_for_unplayed_weeks(self):
        """0.0 means eliminated. An unplayed week must not claim that."""
        season = {
            "year": 2026,
            "roster": ["Amir", "Andy"],
            "sheet": {"first_week": 0, "last_week": 18, "range": "B2:M20"},
            "snapshots": [{"week": 0, "weighted": {"Amir": 8.6, "Andy": 15.1}}],
        }
        rows = sheets.as_rows(season)
        self.assertEqual(len(rows), 19)
        self.assertEqual(rows[0], [8.6, 15.1])
        self.assertEqual(rows[1], ["", ""])


class TestChart(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(SKILL, "data", "season_2025_weekly.csv")) as fh:
            rows = list(csv.DictReader(fh))
        self.roster = [c for c in rows[0] if c != "week"]
        self.board = {int(r["week"]): {n: float(r[n]) for n in self.roster} for r in rows}

    def test_week_file_contains_no_future_weeks(self):
        """This is the whole immutability guarantee."""
        for week in (0, 7, 13, 18):
            payload = chart.build_payload(sorted(self.board), self.board, self.roster,
                                          year=2025, upto_week=week)
            self.assertEqual(payload["weeks"], list(range(week + 1)))
            self.assertEqual(len(payload["series"][0]["values"]), week + 1)

    def test_elimination_week_is_detected(self):
        payload = chart.build_payload(sorted(self.board), self.board, self.roster,
                                      year=2025, upto_week=18)
        by_name = {s["name"]: s for s in payload["series"]}
        # Hanan's odds hit 0.0 at week 4 in the verified data and never recover.
        self.assertEqual(by_name["Hanan"]["eliminatedAt"], 4)
        self.assertIsNone(by_name["Pop"]["eliminatedAt"])   # Pop wins it

    def test_standalone_html_is_self_contained(self):
        html = chart.render(sorted(self.board), self.board, self.roster,
                            year=2025, upto_week=7)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("fetch(", html)
        self.assertIn("W8", "".join(chart.week_label(w) for w in range(9)))
        self.assertNotIn('"W8"', html)   # week 8 data is absent, not merely hidden


class TestStatpack(unittest.TestCase):

    def test_no_em_or_en_dashes(self):
        """Jacob's standing house rule."""
        old = load_2025()
        picks = {n.capitalize(): v for n, v in old.picks_dict.items()}
        guesses = {n.capitalize(): v for n, v in old.predicted_points.items()}
        season = {
            "year": 2025,
            "roster": sorted(picks),
            "picks": picks,
            "points_guess": guesses,
            "division_indices": old.division_weeks,
            "week_to_game_index": {str(i + 1): i for i in range(17)},
            "bye_week": None,
            "snapshots": [],
            "model": {},
            "games": [
                {"index": i, "nfl_week": i + 1, "label": "Game {}".format(i + 1),
                 "result": old.eagles_results[i] if i < 9 else "A",
                 "points_for": SCORES_2025[i] if i < 9 else None,
                 "weight": old.weight[i], "division": i in old.division_weeks}
                for i in range(17)
            ],
        }
        from fep import season as season_mod
        board = season_mod.run(season)
        text = statpack.render(season, board, week=10)
        for dash in statpack.BANNED:
            self.assertNotIn(dash, text, "found a banned dash in the stat pack")
        self.assertIn("Decision Tree", text)
        self.assertIn("Leverage Index", text)



class TestHistory(unittest.TestCase):
    """Ten seasons of record, and the quirks that make them awkward."""

    @classmethod
    def setUpClass(cls):
        from fep import history
        cls.H = history
        cls.seasons = history.weekly_picks()

    def test_every_season_loads(self):
        self.assertEqual(sorted(self.seasons), list(range(2016, 2026)))

    def test_every_season_has_six_division_games(self):
        """The NFC East plays home and away, always. A parsing slip shows here."""
        for year, season in self.seasons.items():
            self.assertEqual(len(season["division_indices"]), 6,
                             "{} found {} division games".format(
                                 year, len(season["division_indices"])))

    def test_pick_sheets_are_index_aligned(self):
        for year, season in self.seasons.items():
            games = len(season["results"])
            for name, sheet in season["picks"].items():
                self.assertEqual(len(sheet), games,
                                 "{} {} has {} picks for {} games".format(
                                     year, name, len(sheet), games))

    def test_giants_are_division_but_jets_are_not(self):
        for name in ("Giants", "at Giants", "New York Giants", "Cowboys",
                     "at Dallas", "Redskins", "Washington", "Football Team",
                     "Commanders"):
            self.assertTrue(self.H.is_division(name), name)
        for name in ("New York Jets", "at Jets", "Bears", "at Rams", ""):
            self.assertFalse(self.H.is_division(name), name)

    def test_2020_tie_is_excluded(self):
        """It counted for nobody, and the totals only reconcile that way."""
        season = self.seasons[2020]
        self.assertEqual(len(season["results"]), 15)   # 16 games minus the tie
        self.assertNotIn(self.H.TIE, season["results"])
        self.assertTrue(any("tie" in n.lower() for n in season["notes"]))

    def test_known_record_discrepancies_are_flagged(self):
        """2016 and 2020 disagree with the record book, on purpose."""
        for year in (2016, 2020):
            notes = " ".join(self.seasons[year]["notes"]).lower()
            self.assertIn("record", notes, "{} should flag its discrepancy".format(year))

    def test_computed_totals_match_the_record_book(self):
        """Every competitor's correct-pick count, recomputed from their picks.

        102 of 104 competitor-seasons reconcile exactly. The two that do not are
        single-cell source-sheet quirks where the stated total is authoritative.
        A new entry here means the pick grids and the record book have drifted,
        which would make any historical claim unsafe to publish.
        """
        unexplained = [r for r in self.H.reconcile_totals() if not r["known"]]
        self.assertEqual(unexplained, [], "unexplained pick-total mismatches")

    def test_reconciliation_covers_every_competitor_season(self):
        checked = sum(len(s["picks"]) for s in self.seasons.values())
        self.assertGreaterEqual(checked, 100)
        self.assertLessEqual(len(self.H.reconcile_totals()), 3)

    def test_retro_reproduces_every_champion(self):
        """The strongest end-to-end check available on the historical data."""
        book = {r["year"]: (r["champion"], r["winning_score"])
                for r in self.H.champions()}
        for year in sorted(self.seasons):
            result = self.H.retro_season(year)
            champion, score = book[year]
            top = max(result["final_correct"].values())
            tied = [n for n, v in result["final_correct"].items() if v == top]
            self.assertEqual(top, score, "{} winning score".format(year))
            self.assertIn(champion, tied, "{} champion not among the leaders".format(year))

    def test_head_to_head_is_symmetric(self):
        a = self.H.head_to_head("Nathan", "Jacob")
        b = self.H.head_to_head("Jacob", "Nathan")
        self.assertEqual(a["a_ahead"], b["b_ahead"])
        self.assertEqual(a["seasons"], b["seasons"])

    def test_context_lines_have_no_banned_dashes(self):
        for name in ("Nathan", "Pop", "Buhduh"):
            for line in self.H.context_lines(name):
                for dash in ("—", "–"):
                    self.assertNotIn(dash, line)

if __name__ == "__main__":
    unittest.main(verbosity=2)
