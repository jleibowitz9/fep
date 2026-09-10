"""The CMS tables, and the one rule they exist to keep.

    A row published in week N must be identical in week N+1.

That is the whole requirement. If it does not hold, an old newsletter silently
changes when a later game is played, which is exactly the failure the per-week
sheet tabs have today.
"""

from __future__ import annotations

import copy
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fep import chart, cms, engine, season as season_mod  # noqa: E402


ROSTER = ["Amir", "Andy", "Buhduh", "Emer", "Hanan", "Jacob",
          "Jay", "Jen", "Marsha", "Nathan", "Pop", "Sarah"]


def build_season(year=2026, games=17, bye_week=10, seed=11):
    """A complete, plausible season with known results, built without ESPN."""
    random.seed(seed)
    schedule, index, week = [], 0, 1
    while index < games:
        if week == bye_week:
            week += 1
            continue
        schedule.append({
            "index": index,
            "nfl_week": week,
            "label": ("@ Team{}" if index % 2 else "vs. Team{}").format(index),
            "result": random.choice([engine.WIN, engine.LOSS]),
            "weight": round(random.uniform(0.35, 0.75), 4),
            "points_for": random.randint(13, 34),
            "points_against": random.randint(10, 31),
            "division": index in (0, 6, 7, 8, 10, 16),
            "date": "{}-09-{:02d}".format(year, 1 + index),
        })
        index += 1
        week += 1

    picks = {name: [random.choice([engine.WIN, engine.LOSS]) for _ in range(games)]
             for name in ROSTER}
    return {
        "year": year,
        "roster": list(ROSTER),
        "picks": picks,
        "points_guess": {n: random.randint(370, 460) for n in ROSTER},
        "colors": chart.colors_for(ROSTER),
        "games": schedule,
        "division_indices": [g["index"] for g in schedule if g["division"]],
        "week_to_game_index": {str(g["nfl_week"]): g["index"] for g in schedule},
        "bye_week": bye_week,
        "bye_weeks": [bye_week],
        "snapshots": [],
        "sheet": dict(season_mod.DEFAULT_SHEET),
        "model": dict(season_mod.DEFAULT_MODEL),
    }


def walk(season, upto):
    """Replay the season week by week, snapshotting as the real run does."""
    weeks = []
    for week in range(0, upto + 1):
        board = season_mod.run(season, through_week=week)
        season_mod.snapshot(season, week, board)
        weeks.append(week)
    return weeks


class ImmutabilityTest(unittest.TestCase):
    """The load-bearing test for the whole design."""

    # games and seasons hold current state on purpose: a result becomes known,
    # a record changes. competitor_seasons tracks a live placing. Everything
    # else is a frozen record of a week that has already happened.
    FROZEN = ("weeks", "standings", "picks")
    LIVE = ("games", "seasons", "competitor_seasons")

    # `picks` is frozen in every column but one. `correct` cannot be, because
    # it is the game's result seen from the pick's side and a result becomes
    # known during the season. It is held to the weaker guarantee instead --
    # blank until settled, then never moving again -- which
    # test_a_settled_pick_never_changes_its_answer asserts. Everything else on
    # the row is still checked cell for cell below.
    LIVE_COLUMNS = {"picks": ("correct",)}

    def setUp(self):
        self.season = build_season()

    def _rows_by_slug(self, table):
        live = self.LIVE_COLUMNS.get(table.name, ())
        return {row["slug"]: {k: v for k, v in row.items() if k not in live}
                for row in table.rows}

    def test_a_frozen_row_never_changes_once_written(self):
        history = {}          # table -> slug -> row, as first published
        first_seen = {}       # table -> slug -> week it appeared
        season = self.season

        for week in range(0, 19):
            board = season_mod.run(season, through_week=week)
            season_mod.snapshot(season, week, board)
            for name, table in cms.tables(season).items():
                if name not in self.FROZEN:
                    continue
                seen = history.setdefault(name, {})
                when = first_seen.setdefault(name, {})
                for slug, row in self._rows_by_slug(table).items():
                    if slug in seen:
                        self.assertEqual(
                            seen[slug], row,
                            "{} row {!r} changed in week {} (first written in "
                            "week {})".format(name, slug, week, when[slug]))
                    else:
                        seen[slug] = copy.deepcopy(row)
                        when[slug] = week

        self.assertEqual(len(history["standings"]), 19 * 12)
        self.assertEqual(len(history["weeks"]), 19)
        self.assertEqual(len(history["picks"]), 18 * 12)   # 17 games + the bye

    def test_a_settled_pick_never_changes_its_answer(self):
        """The guarantee `picks.correct` gets instead of being frozen.

        A cell may fill in exactly once, from blank to True or False. If it can
        move from True to False, or back to blank, the column is a live
        statistic wearing a frozen table's clothes, which is the failure this
        whole module is built to prevent.

        The season is replayed with the results genuinely unknown ahead of
        time, because `build_season` fills every result in up front and a walk
        over that never exercises the transition at all -- `picks_table` reads
        `game["result"]` directly rather than the board, so it would show all
        seventeen games settled in week zero and the test would pass on a
        column that could not move.
        """
        season = self.season
        final = [g["result"] for g in season["games"]]
        for game in season["games"]:
            game["result"] = engine.UNPLAYED

        settled = {}          # slug -> the answer it first showed

        for week in range(0, 19):
            for game in season["games"]:
                if game["nfl_week"] <= week:
                    game["result"] = final[game["index"]]
            for row in cms.tables(season)["picks"].rows:
                answer = row["correct"]
                if answer == "":
                    self.assertNotIn(
                        row["slug"], settled,
                        "{} went back to blank in week {}".format(
                            row["slug"], week))
                    continue
                self.assertIn(answer, (True, False), row["slug"])
                if row["slug"] in settled:
                    self.assertEqual(
                        settled[row["slug"]], answer,
                        "{} changed its answer in week {}".format(
                            row["slug"], week))
                else:
                    settled[row["slug"]] = answer

        # By the end every game has been played, so only the bye is still blank.
        self.assertEqual(len(settled), 17 * 12)

    def test_a_frozen_row_is_never_deleted(self):
        season = self.season
        counts = []
        for week in range(0, 19):
            board = season_mod.run(season, through_week=week)
            season_mod.snapshot(season, week, board)
            counts.append(len(cms.tables(season)["standings"].rows))
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[-1], 19 * 12)

    def test_a_later_result_does_not_leak_into_an_earlier_week(self):
        """The specific way this breaks: week 3 showing week 9's record."""
        season = self.season
        walk(season, 18)
        rows = {r["slug"]: r for r in cms.tables(season)["weeks"].rows}
        wins = sum(1 for g in season["games"]
                   if g["nfl_week"] <= 3 and g["result"] == engine.WIN)
        losses = sum(1 for g in season["games"]
                     if g["nfl_week"] <= 3 and g["result"] == engine.LOSS)
        self.assertEqual((rows["2026-w03"]["wins"], rows["2026-w03"]["losses"]),
                         (wins, losses))

    def test_the_live_tables_are_the_only_ones_that_move(self):
        """Stated as a test so that a future table is a deliberate choice."""
        season = self.season
        walk(season, 5)
        self.assertEqual(sorted(cms.tables(season)),
                         sorted(self.FROZEN + self.LIVE + ("competitors",)))


class CorrectingTheScheduleTest(unittest.TestCase):
    """A schedule correction must not disturb anything already published.

    Slugs used to carry the opponent name, so correcting one label produced a
    whole new set of pick rows and orphaned the originals, because the transport
    never deletes. weeks_table also read today's schedule for historical weeks,
    so a corrected label rewrote a week published months earlier.
    """

    def _rows(self, season):
        return {name: {r["slug"]: dict(r) for r in table.rows}
                for name, table in cms.tables(season).items()}

    def test_renaming_an_opponent_changes_no_slug(self):
        season = build_season()
        walk(season, 18)
        before = self._rows(season)

        season["games"][0]["label"] = "vs. Football Team"
        season["games"][0]["opponent"] = "Football Team"
        after = self._rows(season)

        for name in before:
            self.assertEqual(sorted(before[name]), sorted(after[name]),
                             "{} slugs moved".format(name))

    def test_renaming_an_opponent_does_not_rewrite_a_published_week(self):
        season = build_season()
        walk(season, 18)
        before = self._rows(season)

        season["games"][0]["label"] = "vs. Football Team"
        season["games"][0]["opponent"] = "Football Team"
        after = self._rows(season)

        # weeks and standings and picks are frozen: not one cell may move.
        for name in ("weeks", "standings", "picks"):
            for slug, row in before[name].items():
                self.assertEqual(row, after[name][slug],
                                 "{} {} changed".format(name, slug))

        # games is the live table, so it is allowed to show the correction.
        self.assertEqual(after["games"]["2026-w01"]["away_team"], "Football Team")

    def test_the_frozen_matchup_survives_the_game_disappearing(self):
        """The strongest form: the schedule entry is gone entirely."""
        season = build_season()
        walk(season, 6)
        before = self._rows(season)["weeks"]["2026-w03"]
        season["games"] = [g for g in season["games"] if g["nfl_week"] != 3]
        after = self._rows(season)["weeks"]["2026-w03"]
        self.assertEqual(before, after)


class StructuredGameFieldsTest(unittest.TestCase):
    """Prefer what ESPN recorded over what a display string implies."""

    def test_a_neutral_site_game_is_not_a_home_game(self):
        season = build_season()
        season["games"][4].update({
            "label": "vs. Jaguars (London)", "opponent": "Jaguars",
            "home": False, "neutral_site": True,
            "venue": "Tottenham Hotspur Stadium",
        })
        row = {r["nfl_week"]: r for r in cms.games_table(season).rows}[5]
        # The label says "vs.", the data says otherwise. The data wins, so the
        # Eagles are the away side and the Jaguars are nominally at home.
        self.assertEqual(row["away_team"], cms.EAGLES)
        self.assertEqual(row["away_abbr"], "PHI")
        self.assertEqual(row["home_team"], "Jaguars")
        self.assertTrue(row["neutral_site"])
        self.assertEqual(row["venue"], "Tottenham Hotspur Stadium")

    def test_parsing_is_still_the_fallback(self):
        season = build_season()
        for game in season["games"]:
            for field in ("opponent", "home", "neutral_site", "venue"):
                game.pop(field, None)
        rows = [r for r in cms.games_table(season).rows if not r["is_bye"]]
        self.assertTrue(any(r["away_team"] == cms.EAGLES for r in rows))
        self.assertTrue(any(r["home_team"] == cms.EAGLES for r in rows))

    def test_the_event_id_is_carried_through(self):
        season = build_season()
        season["games"][0]["event_id"] = "401772936"
        row = cms.games_table(season).rows[0]
        self.assertEqual(row["event_id"], "401772936")


class MatchupColumnsTest(unittest.TestCase):
    """games reads as a matchup: who is home, who is away, and their codes."""

    def test_a_home_game_puts_the_eagles_at_home(self):
        season = build_season()
        season["games"][0].update({"label": "vs. Commanders", "home": True,
                                   "opponent": "WSH", "neutral_site": False})
        row = cms.games_table(season).rows[0]
        self.assertEqual((row["home_team"], row["home_abbr"]), (cms.EAGLES, "PHI"))
        self.assertEqual((row["away_team"], row["away_abbr"]), ("Commanders", "WSH"))

    def test_an_away_game_flips_both_sides(self):
        season = build_season()
        season["games"][1].update({"label": "@ Cowboys", "home": False,
                                   "opponent": "DAL", "neutral_site": False})
        row = cms.games_table(season).rows[1]
        self.assertEqual((row["home_team"], row["home_abbr"]), ("Cowboys", "DAL"))
        self.assertEqual((row["away_team"], row["away_abbr"]), (cms.EAGLES, "PHI"))

    def test_a_bye_row_says_BYE_in_both_abbreviations(self):
        season = build_season()
        row = [r for r in cms.games_table(season).rows if r["is_bye"]][0]
        self.assertEqual((row["home_abbr"], row["away_abbr"]), ("BYE", "BYE"))
        self.assertEqual(row["label"], "Bye")

    def test_no_real_game_uses_the_bye_abbreviation(self):
        season = build_season()
        for row in cms.games_table(season).rows:
            if row["is_bye"]:
                continue
            self.assertNotIn("BYE", (row["home_abbr"], row["away_abbr"]))

    def test_the_eagles_appear_in_every_non_bye_row(self):
        season = build_season()
        for row in cms.games_table(season).rows:
            if row["is_bye"]:
                continue
            self.assertIn(cms.EAGLES, (row["home_team"], row["away_team"]))
            self.assertIn("PHI", (row["home_abbr"], row["away_abbr"]))

    def test_every_nfl_week_has_exactly_one_row(self):
        season = build_season()
        rows = cms.games_table(season).rows
        weeks = [r["nfl_week"] for r in rows]
        self.assertEqual(weeks, sorted(weeks))
        self.assertEqual(len(weeks), len(set(weeks)))
        self.assertEqual(weeks, list(range(1, max(weeks) + 1)))


class SpreadsheetCoercionTest(unittest.TestCase):
    """Google Sheets rewrites some strings on the way in.

    "5-2" is stored as the 5th of February and read back as a Date, so the
    value written and the value stored are different things. On a frozen table
    that also means every replay looks like a change. Caught by the frozen
    guard on a live push, which is the guard doing exactly its job.
    """

    import re as _re
    # What Sheets will read as a date or a time rather than as text.
    DATEISH = _re.compile(r"^\s*\d{1,4}\s*[-/.]\s*\d{1,2}(\s*[-/.]\s*\d{1,4})?\s*$")
    TIMEISH = _re.compile(r"^\s*\d{1,2}:\d{2}")

    ALLOWED = {("games", "kickoff")}          # a date column, meant to be a date

    def test_no_string_cell_will_be_read_as_a_date(self):
        season = build_season()
        walk(season, 18)
        for name, table in cms.tables(season).items():
            for row in table.rows:
                for column, value in row.items():
                    if (name, column) in self.ALLOWED:
                        continue
                    if not isinstance(value, str):
                        continue
                    self.assertIsNone(
                        self.DATEISH.match(value),
                        "{}.{} = {!r} would be stored as a date".format(
                            name, column, value))
                    self.assertIsNone(self.TIMEISH.match(value), value)

    def test_the_record_is_two_numbers(self):
        season = build_season()
        walk(season, 7)
        row = {r["slug"]: r for r in cms.tables(season)["weeks"].rows}["2026-w07"]
        self.assertIsInstance(row["wins"], int)
        self.assertIsInstance(row["losses"], int)
        self.assertEqual(row["wins"] + row["losses"], 7)


class FinalIsNotAGuessTest(unittest.TestCase):
    """A season is final when the board that settles it exists, not before."""

    def test_a_completed_schedule_without_the_final_board_is_not_final(self):
        """Reproduces the reported case: every game played, latest board is
        week 16, and the week 16 leader was crowned champion."""
        season = build_season()
        for week in range(0, 17):
            board = season_mod.run(season, through_week=week)
            season_mod.snapshot(season, week, board)
        tables = cms.tables(season)
        row = tables["seasons"].rows[0]
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual(row["champion"], "")
        self.assertEqual(row["champion_correct"], "")
        for entry in tables["competitor_seasons"].rows:
            self.assertFalse(entry["is_champion"], entry["name"])

    def test_the_final_board_settles_it(self):
        season = build_season()
        walk(season, 18)
        tables = cms.tables(season)
        row = tables["seasons"].rows[0]
        self.assertEqual(row["status"], "final")
        self.assertTrue(row["champion"])
        champions = {e["name"] for e in tables["competitor_seasons"].rows
                     if e["is_champion"]}
        # The two tables must name the same winner. They used to be able to
        # disagree: one picked a single name, the other marked every rank 1.
        named = {row["champion"]} | {n.strip() for n in
                                     row["co_champions"].split(",") if n.strip()}
        self.assertEqual(champions, named)

    def test_an_unsettled_final_week_is_still_in_progress(self):
        """A board covering the last week but with more than one outcome left
        has not settled anything."""
        season = build_season()
        walk(season, 18)
        season["snapshots"][-1]["remaining_outcomes"] = 4
        self.assertEqual(cms.tables(season)["seasons"].rows[0]["status"],
                         "in_progress")


class EliminationTest(unittest.TestCase):
    """Zero this week is not the same as finished."""

    def _season_with(self, sequences):
        season = build_season()
        season["snapshots"] = []
        for week, board in enumerate(sequences):
            season["snapshots"].append({
                "week": week, "weighted": board,
                "straight": board, "current_points": {n: 0 for n in board},
                "remaining_outcomes": 2, "results": [], "deciding": {},
                "eliminated": sorted(n for n, v in board.items() if v == 0.0),
            })
        return season

    def test_a_competitor_who_recovers_was_not_eliminated(self):
        """Reproduces the reported disagreement: 0.0 one week, 5.0 the next.
        The CMS said eliminated in week 1; the chart said still alive."""
        season = self._season_with([
            {"Amir": 50.0, "Andy": 50.0},
            {"Amir": 0.0, "Andy": 100.0},
            {"Amir": 5.0, "Andy": 95.0},
        ])
        self.assertIsNone(cms.eliminated_week(season, "Amir"))

    def test_the_final_run_of_zeros_is_the_elimination(self):
        season = self._season_with([
            {"Amir": 50.0}, {"Amir": 0.0}, {"Amir": 5.0},
            {"Amir": 0.0}, {"Amir": 0.0},
        ])
        self.assertEqual(cms.eliminated_week(season, "Amir"), 3)

    def test_someone_still_alive_has_no_elimination_week(self):
        season = self._season_with([{"Amir": 50.0}, {"Amir": 20.0}])
        self.assertIsNone(cms.eliminated_week(season, "Amir"))

    def test_it_agrees_with_the_chart(self):
        season = build_season()
        walk(season, 18)
        boards = {s["week"]: s["weighted"] for s in season["snapshots"]}
        out = {s["week"]: s["eliminated"] for s in season["snapshots"]}
        weeks = sorted(boards)
        series = chart.build_series(weeks, boards, season["roster"],
                                    eliminated=out)
        for entry in series:
            self.assertEqual(
                cms.eliminated_week(season, entry["name"]),
                entry["eliminated_at"],
                "{} disagrees with the chart".format(entry["name"]))

    def test_rounding_does_not_bury_someone_at_a_twentieth_of_a_percent(self):
        """0.04% rounds to 0.0 on the board but is not elimination."""
        season = self._season_with([{"Amir": 50.0}, {"Amir": 0.0}])
        season["snapshots"][1]["eliminated"] = []     # unrounded: still alive
        self.assertIsNone(cms.eliminated_week(season, "Amir"))
        season["snapshots"][1]["eliminated"] = ["Amir"]
        self.assertEqual(cms.eliminated_week(season, "Amir"), 1)


class WeekOverWeekChangeTest(unittest.TestCase):

    def test_change_is_blank_when_the_previous_week_is_missing(self):
        """A gap made a two-week move look like a one-week move."""
        season = build_season()
        walk(season, 8)
        season["snapshots"] = [s for s in season["snapshots"] if s["week"] != 6]
        rows = {r["slug"]: r for r in cms.tables(season)["standings"].rows}
        self.assertEqual(rows["2026-w07-amir"]["change"], "")
        self.assertNotEqual(rows["2026-w08-amir"]["change"], "")

    def test_the_first_week_has_no_change(self):
        season = build_season()
        walk(season, 2)
        rows = {r["slug"]: r for r in cms.tables(season)["standings"].rows}
        self.assertEqual(rows["2026-w00-amir"]["change"], "")
        self.assertNotEqual(rows["2026-w01-amir"]["change"], "")

    def test_a_bye_week_does_not_break_the_chain(self):
        season = build_season()
        walk(season, 12)
        rows = {r["slug"]: r for r in cms.tables(season)["standings"].rows}
        self.assertNotEqual(rows["2026-w10-amir"]["change"], "")   # the bye
        self.assertNotEqual(rows["2026-w11-amir"]["change"], "")


class ColumnOrderTest(unittest.TestCase):
    """New columns are appended, never inserted.

    Framer maps a sheet column to a CMS field. Inserting a column shifts every
    column after it, and if any of that mapping is positional the shift is
    silent: a field keeps its name and starts showing the neighbouring column's
    values.
    """

    # The order as published. Anything new belongs after these, not among them.
    PUBLISHED = {
        "picks": ["slug", "season", "week_ref", "nfl_week", "game",
                  "competitor", "name", "pick"],
        "standings": ["slug", "season", "week", "week_ref", "competitor",
                      "name", "weighted", "straight", "correct", "rank",
                      "change", "is_eliminated", "is_bye"],
        "competitors": ["slug", "name", "color", "first_season",
                        "seasons_played", "titles", "title_years",
                        "career_points", "all_time_rank"],
    }

    def test_published_columns_keep_their_position(self):
        season = build_season()
        walk(season, 3)
        tables = cms.tables(season)
        for name, published in self.PUBLISHED.items():
            actual = list(tables[name].columns)
            self.assertEqual(actual[:len(published)], published,
                             "{} reordered its published columns".format(name))

    def test_slug_is_always_first(self):
        """The Apps Script matches rows on column A."""
        season = build_season()
        walk(season, 3)
        for name, table in cms.tables(season).items():
            self.assertEqual(table.columns[0], "slug", name)


class SlugTest(unittest.TestCase):

    def test_every_slug_carries_the_year(self):
        """Without it, 2027 week 1 upserts onto 2026 week 1."""
        season = build_season()
        walk(season, 3)
        for name, table in cms.tables(season).items():
            if name == "competitors":
                continue          # a person spans seasons, by design
            for row in table.rows:
                self.assertIn("2026", row["slug"],
                              "{} slug {!r} has no year".format(name, row["slug"]))

    def test_weeks_are_zero_padded_so_they_sort(self):
        season = build_season()
        walk(season, 12)
        slugs = [r["slug"] for r in cms.tables(season)["weeks"].rows]
        self.assertEqual(slugs, sorted(slugs))

    def test_slugs_are_unique_within_every_table(self):
        season = build_season()
        walk(season, 18)
        for name, table in cms.tables(season).items():
            slugs = [r["slug"] for r in table.rows]
            self.assertEqual(len(slugs), len(set(slugs)), name)

    def test_two_seasons_never_collide(self):
        a = cms.tables(build_season(2026))
        b = cms.tables(build_season(2027))
        for name in a:
            if name == "competitors":
                continue
            overlap = {r["slug"] for r in a[name].rows} & {r["slug"] for r in b[name].rows}
            self.assertEqual(overlap, set(), name)


class ShapeTest(unittest.TestCase):

    def test_a_partial_field_only_publishes_who_submitted(self):
        """September: seven sheets in, five outstanding."""
        season = build_season()
        for name in ("Amir", "Jay", "Jen", "Marsha", "Sarah"):
            season["picks"][name] = []
        tables = cms.tables(season)
        self.assertEqual(len(tables["picks"].rows), 18 * 7)   # 17 games + the bye
        self.assertEqual(len(tables["competitor_seasons"].rows), 7)
        # the roster is still twelve: they exist, they just have not answered
        self.assertEqual(len(tables["competitors"].rows), 12)

    def test_a_rookie_is_not_an_error(self):
        season = build_season()
        season["roster"].append("Dave")
        season["picks"]["Dave"] = [engine.WIN] * 17
        season["points_guess"]["Dave"] = 400
        season["colors"] = chart.colors_for(season["roster"])
        rows = {r["name"]: r for r in cms.tables(season)["competitors"].rows}
        self.assertEqual(rows["Dave"]["first_season"], 2026)
        self.assertEqual(rows["Dave"]["titles"], 0)
        self.assertEqual(rows["Dave"]["color"], season["colors"]["Dave"])

    def test_matrix_starts_with_the_header(self):
        table = cms.tables(build_season())["games"]
        matrix = table.matrix()
        self.assertEqual(matrix[0], list(table.columns))
        self.assertEqual(len(matrix), 1 + len(table.rows))
        for row in matrix[1:]:
            self.assertEqual(len(row), len(table.columns))

    def test_no_cell_is_the_string_None(self):
        season = build_season()
        walk(season, 4)
        for name, table in cms.tables(season).items():
            for row in table.matrix()[1:]:
                for cell in row:
                    self.assertIsNotNone(cell, name)
                    self.assertNotEqual(cell, "None", name)

    def test_a_bye_week_gets_a_row_with_no_game(self):
        season = build_season()
        walk(season, 12)
        rows = {r["slug"]: r for r in cms.tables(season)["weeks"].rows}
        bye = rows["2026-w10"]
        self.assertTrue(bye["is_bye"])
        self.assertEqual(bye["game"], "")
        self.assertEqual(bye["game_label"], "Bye")

    def test_an_eighteen_game_season_produces_the_right_shape(self):
        season = build_season(2031, games=18, bye_week=7)
        walk(season, 19)
        tables = cms.tables(season)
        # 18 games plus a row for the bye, because every NFL week gets a row.
        self.assertEqual(len(tables["games"].rows), 19)
        self.assertEqual(sum(1 for r in tables["games"].rows if r["is_bye"]), 1)
        self.assertEqual(len(tables["picks"].rows), 19 * 12)   # 18 games + a bye
        self.assertEqual(len(tables["standings"].rows), 20 * 12)


class SeasonColumnTest(unittest.TestCase):
    """The Apps Script protects past seasons by reading this column.

    If a table ever ships without it, the script refuses the whole write. These
    assert the contract from the Python side so the failure is caught here
    rather than on a live push.
    """

    def test_every_table_names_its_season(self):
        season = build_season()
        walk(season, 2)
        for name, table in cms.tables(season).items():
            if name == "competitors":
                continue          # spans seasons by design
            self.assertTrue(
                "season" in table.columns or "year" in table.columns,
                "{} has no season column".format(name))

    def test_year_and_season_are_never_both_present(self):
        """Two names for one fact is how a component gets bound to the wrong one."""
        season = build_season()
        walk(season, 2)
        for name, table in cms.tables(season).items():
            self.assertFalse("season" in table.columns and "year" in table.columns,
                             "{} has both".format(name))

    def test_colour_lives_only_in_competitors(self):
        season = build_season()
        walk(season, 2)
        for name, table in cms.tables(season).items():
            if name == "competitors":
                self.assertIn("color", table.columns)
            else:
                self.assertNotIn("color", table.columns, name)


class OneKeyPerWeekTest(unittest.TestCase):
    """The home screen holds one value and drives three lists with it."""

    HOME_SCREEN = ("games", "picks", "standings")

    def test_every_home_screen_table_shares_the_key(self):
        season = build_season()
        walk(season, 7)
        for name in self.HOME_SCREEN:
            self.assertIn("week_ref", cms.tables(season)[name].columns, name)

    def test_the_key_is_a_real_weeks_slug(self):
        """A filter that matches nothing is worse than one that errors."""
        season = build_season()
        walk(season, 18)
        tables = cms.tables(season)
        known = {row["slug"] for row in tables["weeks"].rows}
        for name in self.HOME_SCREEN:
            for row in tables[name].rows:
                self.assertIn(row["week_ref"], known,
                              "{} points at {}, which is not a week".format(
                                  name, row["week_ref"]))

    def test_one_value_selects_one_week_everywhere(self):
        season = build_season()
        walk(season, 18)
        tables = cms.tables(season)
        key = "2026-w07"
        selected = {name: [r for r in tables[name].rows if r["week_ref"] == key]
                    for name in self.HOME_SCREEN}
        self.assertEqual(len(selected["games"]), 1)       # one game that week
        self.assertEqual(len(selected["picks"]), 12)      # one pick each
        self.assertEqual(len(selected["standings"]), 12)  # one row each

    def test_the_bye_week_selects_a_board_and_a_bye_row(self):
        """A bye is a week with no matchup, not a week that does not exist.

        It used to select nothing from games, so a schedule laid out from that
        table silently skipped a week.
        """
        season = build_season()
        walk(season, 18)
        tables = cms.tables(season)
        key = "2026-w10"                                   # the bye
        games = [r for r in tables["games"].rows if r["week_ref"] == key]
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0]["is_bye"])
        self.assertEqual(games[0]["label"], "Bye")
        self.assertEqual(games[0]["home_team"], "")
        self.assertEqual(games[0]["away_team"], "")
        # The abbreviation slots are what a matchup is laid out from, so they
        # say BYE rather than leaving a pair of blanks.
        self.assertEqual(games[0]["home_abbr"], "BYE")
        self.assertEqual(games[0]["away_abbr"], "BYE")
        self.assertEqual(
            len([r for r in tables["standings"].rows if r["week_ref"] == key]), 12)
        # Everyone gets a row, flagged as a bye and holding no pick, so a grid
        # laid out from this table has no hole where the week should be.
        picks = [r for r in tables["picks"].rows if r["week_ref"] == key]
        self.assertEqual(len(picks), 12)
        self.assertTrue(all(r["is_bye"] for r in picks))
        self.assertTrue(all(r["pick"] == "" for r in picks))
        # ...and no game index was consumed by it
        self.assertEqual(
            sum(1 for r in tables["picks"].rows
                if r["competitor"] == "amir" and r["pick"] in ("W", "L")), 17)


class CorrectColumnTest(unittest.TestCase):
    """`picks.correct`, the one live cell on an otherwise frozen row.

    It has to agree with the board, so it is scored the way
    `engine.correct_picks_so_far` scores it and checked against it here. The
    interesting cases are the three that are not True or False.
    """

    def _rows(self, season):
        return {r["slug"]: r for r in cms.picks_table(season).rows}

    def test_a_pick_matching_the_result_is_correct(self):
        season = build_season()
        rows = self._rows(season)
        for name in ROSTER:
            sheet = season["picks"][name]
            for game in season["games"]:
                slug = "{}-{}".format(
                    cms.game_slug(2026, game["nfl_week"]), cms._slugify(name))
                self.assertEqual(rows[slug]["correct"],
                                 sheet[game["index"]] == game["result"], slug)

    def test_the_column_agrees_with_the_board(self):
        """The failure worth catching: a second way to score, scoring it
        differently. The count of True cells per competitor must be the number
        the engine already reports."""
        season = build_season()
        rows = cms.picks_table(season).rows
        expected = engine.correct_picks_so_far(
            season["picks"], [g["result"] for g in season["games"]])
        for name in ROSTER:
            counted = sum(1 for r in rows
                          if r["name"] == name and r["correct"] is True)
            self.assertEqual(counted, expected[name], name)

    def test_an_unplayed_game_is_blank_rather_than_wrong(self):
        """False is a claim the pick was wrong. Before kickoff there is no
        claim to make, and rendering one as a red cross is a lie."""
        season = build_season()
        season["games"][4]["result"] = engine.UNPLAYED
        rows = self._rows(season)
        week = season["games"][4]["nfl_week"]
        slug = "{}-amir".format(cms.game_slug(2026, week))
        self.assertEqual(rows[slug]["correct"], "")
        self.assertIn(rows[slug]["pick"], ("W", "L"))    # the pick still stands

    def test_the_bye_is_blank(self):
        season = build_season()
        rows = [r for r in cms.picks_table(season).rows if r["is_bye"]]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["correct"] == "" for r in rows))

    def test_a_tie_counts_for_nobody(self):
        """Settled, so not blank -- but no pick is ever 'T', so everyone is
        wrong. That is how the family scored the 2020 Bengals game."""
        season = build_season()
        season["games"][2]["result"] = engine.TIE
        week = season["games"][2]["nfl_week"]
        key = cms.game_slug(2026, week)
        rows = [r for r in cms.picks_table(season).rows if r["week_ref"] == key]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["correct"] is False for r in rows))

    def test_correcting_a_result_corrects_the_column(self):
        """The reason not to cache this in the season file: it has to follow a
        manual override, and a stored copy would silently disagree."""
        season = build_season()
        game = season["games"][6]
        slug = "{}-amir".format(cms.game_slug(2026, game["nfl_week"]))
        before = self._rows(season)[slug]["correct"]
        game["result"] = engine.LOSS if game["result"] == engine.WIN else engine.WIN
        self.assertEqual(self._rows(season)[slug]["correct"], not before)


class LabelTest(unittest.TestCase):
    """ESPN hands us one string doing three jobs."""

    def test_a_neutral_site_game(self):
        self.assertEqual(cms.split_label("vs. Jaguars (London)"), {
            "opponent": "Jaguars", "home_away": "home",
            "venue": "London", "neutral_site": True})

    def test_an_ordinary_home_game(self):
        self.assertEqual(cms.split_label("vs. Commanders"), {
            "opponent": "Commanders", "home_away": "home",
            "venue": "", "neutral_site": False})

    def test_an_away_game(self):
        self.assertEqual(cms.split_label("@ Cowboys"), {
            "opponent": "Cowboys", "home_away": "away",
            "venue": "", "neutral_site": False})

    def test_an_away_neutral_site_game(self):
        self.assertEqual(cms.split_label("@ Dolphins (Madrid)"), {
            "opponent": "Dolphins", "home_away": "away",
            "venue": "Madrid", "neutral_site": True})

    def test_the_venue_never_reaches_the_opponent_or_the_slug(self):
        for label in ("vs. Jaguars (London)", "@ Dolphins (Madrid)"):
            self.assertNotIn("(", cms.split_label(label)["opponent"])
            self.assertNotIn("(", cms._opponent_slug(label))


if __name__ == "__main__":
    unittest.main(verbosity=2)
