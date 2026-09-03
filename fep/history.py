"""
Ten seasons of FEP history, queryable.

This exists so no number in a newsletter is ever quoted from memory. Every
"first time since", every career stat, every head-to-head is computed from the
record.

SOURCES
-------
The authoritative CSVs in the fep-master skill's data directory:

    champions_by_season.csv          one row per season, 2016 to 2025
    all_time_totals.csv              career totals per competitor
    season_results_by_competitor.csv every finish, every season
    weekly_picks_all_seasons.csv     game-by-game picks, 2016 to 2023
    season_2024_weekly.csv           2024 weekly weighted board
    season_2025_weekly.csv           2025 weekly weighted board

Game-by-game picks for 2024 and 2025 are not in the CSVs; they are read from
Jacob's simulator files in the sibling year folders.

DATA QUIRKS THAT MUST BE HONOURED
---------------------------------
* 2016 Week 16 really was a WIN (Eagles beat the Giants 24-19) but the family's
  sheet scored it a loss, and every 2016 total was computed against that loss.
  The record book therefore shows 6-10 where real life shows 7-9. This module
  stays faithful to how the family scored it, and flags it.
* 2017 left the meaningless Week 17 finale uncounted, so the FEP shows a 13-2
  tracked season against a real 13-3.
* 2020 Week 3 against the Bengals was a TIE. It counted for nobody, and the
  season totals reconcile exactly on that basis. For simulation it is dropped,
  which is equivalent: a game that awards everyone zero cannot change the
  standings.
* Bye weeks appear as blank rows in some seasons and are simply absent in
  others. Both are dropped.
* Seasons before 2021 were 16 games. The roster grew over time: 8 competitors in
  2016, 10 by 2017, 11 in 2022, and the full 12 only from 2024.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional, Sequence

from . import engine

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
_YEARS_ROOT = os.path.dirname(_PROJECT)      # the "FEP Data Center" folder

DEFAULT_DATA_DIR = os.environ.get("FEP_DATA_DIR") or os.path.expanduser(
    "~/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/"
    "d1014f01-77c2-4a2b-bb91-a8c459904777/a772b5d9-f193-460e-9d65-086a1d1f8efc/"
    "skills/fep-master/data"
)

# NFC East, across every name Washington has used in the record.
DIVISION_TOKENS = ("cowboys", "dallas", "giants", "commanders", "redskins",
                   "washington", "football team")

TIE = "T"

_cache: Dict[str, object] = {}


class HistoryError(RuntimeError):
    pass


def _rows(filename: str, data_dir: Optional[str] = None) -> List[dict]:
    path = os.path.join(data_dir or DEFAULT_DATA_DIR, filename)
    if not os.path.exists(path):
        raise HistoryError(
            "cannot find {}. Set FEP_DATA_DIR to the fep-master skill's data "
            "folder.".format(path)
        )
    with open(path) as fh:
        # Some files carry leading comment lines.
        lines = [line for line in fh if not line.startswith("#")]
    return list(csv.DictReader(lines))


def _num(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


# ---------------------------------------------------------------------------
# opponents
# ---------------------------------------------------------------------------

def normalize_opponent(raw: str) -> str:
    """'at New York Giants' -> 'new york giants'. Empty means a bye."""
    return re.sub(r"^at\s+", "", (raw or "").strip(), flags=re.I).lower()


def is_division(raw: str) -> bool:
    """True for an NFC East opponent.

    Careful with New York: the Giants are division, the Jets are not, and both
    appear in the record as 'New York ...'.
    """
    name = normalize_opponent(raw)
    if not name or "jets" in name:
        return False
    return any(token in name for token in DIVISION_TOKENS)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def champions(data_dir: Optional[str] = None) -> List[dict]:
    key = "champions"
    if key not in _cache:
        out = []
        for row in _rows("champions_by_season.csv", data_dir):
            out.append({
                "season": _num(row["Season"]),
                "year": _num(row["Year"]),
                "games": _num(row["Games"]),
                "record": row["EaglesRecord"],
                "winning_score": _num(row["WinningScore"]),
                "champion": row["Champion"],
                "co_champions": [n for n in (row.get("CoChampionsTied") or "").split(",") if n.strip()],
                "field_average": _num(row["FieldAvgCorrect"]),
                "notes": row.get("Notes", ""),
            })
        _cache[key] = sorted(out, key=lambda r: r["year"])
    return _cache[key]


def career_totals(data_dir: Optional[str] = None) -> Dict[str, dict]:
    key = "career"
    if key not in _cache:
        out = {}
        for row in _rows("all_time_totals.csv", data_dir):
            out[row["Competitor"]] = {
                "place": _num(row["Place"]),
                "championships": _num(row["Championships"]),
                "points": _num(row["TotalPoints"]),
                "predicted_record": row["PredictedRecord"],
                "predicted_division_record": row["PredictedDivRecord"],
                "top3": _num(row["Top3Finishes"]),
                "bottom3": _num(row["Bottom3Finishes"]),
            }
        _cache[key] = out
    return _cache[key]


def season_results(data_dir: Optional[str] = None) -> List[dict]:
    key = "results"
    if key not in _cache:
        out = []
        for row in _rows("season_results_by_competitor.csv", data_dir):
            out.append({
                "year": _num(row["Year"]),
                "name": row["Competitor"],
                "place": _num(row["Place"]),
                "champion": row["Championship"] == "1",
                "correct": _num(row["CorrectPicks"]),
                "predicted_wins": _num(row["PredictedWins"]),
                "predicted_division_wins": _num(row["PredictedDivWins"]),
                "top3": row["Top3"] == "1",
                "bottom3": row["Bottom3"] == "1",
            })
        _cache[key] = out
    return _cache[key]


def weekly_boards(data_dir: Optional[str] = None) -> Dict[int, Dict[int, Dict[str, float]]]:
    """{year: {week: {name: weighted %}}} for the seasons that have one.

    2024's figures do not normalise to 100% (a pre-Algorithm-2.0 quirk where
    ties counted fully for each tied competitor). Rankings are trustworthy;
    absolute numbers are as-displayed.
    """
    key = "boards"
    if key not in _cache:
        out = {}
        for year in (2024, 2025):
            try:
                rows = _rows("season_{}_weekly.csv".format(year), data_dir)
            except HistoryError:
                continue
            board = {}
            for row in rows:
                week = _num(row["week"])
                board[week] = {k: float(v) for k, v in row.items()
                               if k != "week" and v not in ("", None)}
            out[year] = board
        _cache[key] = out
    return _cache[key]


# ---------------------------------------------------------------------------
# game-by-game picks
# ---------------------------------------------------------------------------

_PICKS_RE = re.compile(r"picks_dict\s*=\s*\{(.*?)\n\s*\}", re.S)
_ROW_RE = re.compile(r"'(\w+)'\s*:\s*\[(.*?)\]", re.S)
_RESULTS_RE = re.compile(r"eagles_results\s*=\s*\[(.*?)\]", re.S)


def _parse_simulator(path: str) -> Optional[dict]:
    """Pull picks and results out of one of Jacob's simulator files."""
    if not os.path.exists(path):
        return None
    text = open(path).read()

    picks_block = _PICKS_RE.search(text)
    if not picks_block:
        return None
    picks = {}
    for name, body in _ROW_RE.findall(picks_block.group(1)):
        picks[name.capitalize()] = [
            cell.strip().strip("'\"") for cell in body.split(",") if cell.strip()
        ]

    results = None
    results_block = _RESULTS_RE.search(text)
    if results_block:
        results = re.findall(r"'([WLA])'", results_block.group(1))

    return {"picks": picks, "results": results}


def _espn_season(year: int) -> Optional[dict]:
    """Results, opponents and division games for a year, from ESPN (cached).

    Returns None if ESPN cannot be reached and nothing is cached, so the rest of
    the module still works offline.
    """
    key = "espn_{}".format(year)
    if key in _cache:
        return _cache[key]
    try:
        from . import espn
        games = espn.fetch_schedule(year)
    except Exception:
        _cache[key] = None
        return None
    if any(g["result"] == engine.UNPLAYED for g in games):
        _cache[key] = None
        return None
    _cache[key] = {
        "results": [g["result"] for g in games],
        "labels": [g["label"] for g in games],
        "division_indices": [g["index"] for g in games if g["division"]],
        "weeks": [g["nfl_week"] for g in games],
    }
    return _cache[key]


def _season_from_simulator(year: int) -> Optional[dict]:
    """2024 and 2025 picks live in the year folders, not the CSVs.

    Jacob's 2024 file was left unfinished (its last two games are still 'A'), so
    results and division games are taken from ESPN, which is authoritative for
    what actually happened. The reconstructed record is cross-checked against
    the FEP record book, and any disagreement is reported rather than hidden:
    the family's sheet and real life have genuinely diverged before (2016).
    """
    candidates = [
        os.path.join(_YEARS_ROOT, str(year), "simulator.py"),
        os.path.join(_YEARS_ROOT, str(year), "FEP {}.py".format(year)),
    ]
    for path in candidates:
        parsed = _parse_simulator(path)
        if not parsed or not parsed["picks"]:
            continue

        results = parsed["results"] or []
        notes = []
        official = _espn_season(year)

        if engine.UNPLAYED in results or not results:
            if not official:
                continue  # cannot complete this season, skip it
            filled = sum(1 for r in results if r == engine.UNPLAYED) or len(official["results"])
            notes.append(
                "{} game(s) were still unplayed in {}; results taken from "
                "ESPN.".format(filled, os.path.basename(path)))
            results = list(official["results"])

        book = {row["year"]: row["record"] for row in champions()}
        record = "{}-{}".format(results.count(engine.WIN), results.count(engine.LOSS))
        if year in book and book[year] != record:
            notes.append("Reconstructed record {} does not match the record "
                         "book's {}.".format(record, book[year]))

        divisions = _DIVISION_BY_YEAR.get(year)
        if divisions is None:
            divisions = (official or {}).get("division_indices") or []

        return {
            "year": year,
            "picks": parsed["picks"],
            "results": results,
            "opponents": (official or {}).get("labels") or [None] * len(results),
            "weeks": (official or {}).get("weeks") or list(range(1, len(results) + 1)),
            "division_indices": divisions,
            "notes": notes,
            "source": os.path.relpath(path, _YEARS_ROOT),
        }
    return None


# Division indices for seasons read from simulator files. 2025's are Jacob's own
# and match the ESPN schedule exactly; anything else is derived from ESPN.
_DIVISION_BY_YEAR = {2025: [0, 5, 7, 10, 14, 16]}


def weekly_picks(data_dir: Optional[str] = None) -> Dict[int, dict]:
    """Game-by-game picks for every season we have them.

    Returns {year: {weeks, opponents, results, picks, division_indices, notes}}
    with bye weeks and the 2020 tie removed, so every array is index-aligned and
    directly usable by the engine.
    """
    key = "picks"
    if key in _cache:
        return _cache[key]

    rows = _rows("weekly_picks_all_seasons.csv", data_dir)
    by_year: Dict[int, dict] = {}
    for row in rows:
        year, week = _num(row["Year"]), _num(row["Week"])
        entry = by_year.setdefault(year, {"games": {}, "picks": {}})
        entry["games"][week] = (row["Opponent"], row["Result"], row.get("RealWorldNote", ""))
        entry["picks"].setdefault(row["Competitor"], {})[week] = row["Pick"]

    out = {}
    for year, entry in by_year.items():
        notes, keep = [], []
        for week in sorted(entry["games"]):
            opponent, result, note = entry["games"][week]
            if not opponent or result not in (engine.WIN, engine.LOSS, TIE):
                continue  # bye
            if result == TIE:
                # Counted for nobody, so dropping it cannot change standings.
                notes.append("Week {} against the {} was a tie and counted for "
                             "nobody; excluded from the model.".format(week, opponent))
                continue
            keep.append(week)
            if note:
                notes.append("Week {}: {}".format(week, note))

        picks = {}
        for name, weeks in entry["picks"].items():
            sheet = [weeks.get(w) for w in keep]
            if any(p not in (engine.WIN, engine.LOSS) for p in sheet):
                continue  # incomplete sheet, leave the competitor out
            picks[name] = sheet

        results = [entry["games"][w][1] for w in keep]

        # Surface any disagreement with the record book rather than leaving it
        # for a reader to trip over. Two are known and legitimate: 2016, where
        # the family scored a real win as a loss and computed every total
        # against that, and 2020, whose tie the book counts in the record but
        # the model drops.
        book = {row["year"]: row["record"] for row in champions()}
        record = "{}-{}".format(results.count(engine.WIN), results.count(engine.LOSS))
        if year in book and book[year] != record:
            notes.append(
                "Modelled record {} differs from the record book's {}. The "
                "model follows how the family actually scored the season, "
                "which is what every competitor total was computed "
                "against.".format(record, book[year]))

        out[year] = {
            "year": year,
            "weeks": keep,
            "opponents": [entry["games"][w][0] for w in keep],
            "results": results,
            "picks": picks,
            "division_indices": [i for i, w in enumerate(keep)
                                 if is_division(entry["games"][w][0])],
            "notes": notes,
            "source": "weekly_picks_all_seasons.csv",
        }

    for year in (2024, 2025):
        season = _season_from_simulator(year)
        if season:
            out[year] = season

    _cache[key] = dict(sorted(out.items()))
    return _cache[key]


# Competitors whose stated season total is off by one from their own pick grid.
# All three are single-cell source-sheet quirks, documented in the fep-master
# data notes: the stated total is treated as authoritative. Flipping the game
# would break every other competitor's reconciliation, so these are not
# game-level scoring differences.
KNOWN_TOTAL_QUIRKS = {(2016, "Amir"), (2017, "Pop"), (2024, "Amir")}


def reconcile_totals() -> List[dict]:
    """Recompute every competitor's season total from their own picks.

    Anything here that is not in KNOWN_TOTAL_QUIRKS means the pick grids and the
    record book have genuinely drifted apart, which is worth knowing before
    quoting either in a newsletter.
    """
    stated = {(r["year"], r["name"]): r["correct"] for r in season_results()}
    out = []
    for year, season in weekly_picks().items():
        for name, sheet in season["picks"].items():
            computed = sum(1 for i, r in enumerate(season["results"]) if sheet[i] == r)
            expected = stated.get((year, name))
            if expected is not None and computed != expected:
                out.append({
                    "year": year, "name": name,
                    "computed": computed, "stated": expected,
                    "known": (year, name) in KNOWN_TOTAL_QUIRKS,
                })
    return out


def seasons_with_picks() -> List[int]:
    return sorted(weekly_picks())


# ---------------------------------------------------------------------------
# career and head to head
# ---------------------------------------------------------------------------

def career(name: str) -> dict:
    """Everything the record knows about one competitor."""
    totals = career_totals().get(name)
    mine = sorted([r for r in season_results() if r["name"] == name],
                  key=lambda r: r["year"])
    if not mine:
        raise HistoryError("no record for {}".format(name))

    titles = [r["year"] for r in mine if r["champion"]]
    best = min(mine, key=lambda r: r["place"])
    worst = max(mine, key=lambda r: r["place"])
    return {
        "name": name,
        "seasons": [r["year"] for r in mine],
        "first_season": mine[0]["year"],
        "championships": len(titles),
        "title_years": titles,
        "best_finish": best["place"],
        "best_finish_year": best["year"],
        "worst_finish": worst["place"],
        "worst_finish_year": worst["year"],
        "average_place": round(sum(r["place"] for r in mine) / len(mine), 2),
        "average_correct": round(sum(r["correct"] for r in mine) / len(mine), 2),
        "best_score": max(r["correct"] for r in mine),
        "worst_score": min(r["correct"] for r in mine),
        "top3": sum(1 for r in mine if r["top3"]),
        "bottom3": sum(1 for r in mine if r["bottom3"]),
        "career_points": (totals or {}).get("points"),
        "all_time_place": (totals or {}).get("place"),
    }


def head_to_head(a: str, b: str) -> dict:
    """Who has finished ahead of whom, and by how much."""
    by_year = {}
    for row in season_results():
        if row["name"] in (a, b):
            by_year.setdefault(row["year"], {})[row["name"]] = row

    shared, a_ahead, b_ahead, ties = [], 0, 0, 0
    for year in sorted(by_year):
        pair = by_year[year]
        if a not in pair or b not in pair:
            continue
        ra, rb = pair[a], pair[b]
        if ra["place"] < rb["place"]:
            a_ahead += 1
            winner = a
        elif rb["place"] < ra["place"]:
            b_ahead += 1
            winner = b
        else:
            ties += 1
            winner = None
        shared.append({"year": year, "winner": winner,
                       a: {"place": ra["place"], "correct": ra["correct"]},
                       b: {"place": rb["place"], "correct": rb["correct"]}})

    return {"a": a, "b": b, "seasons": len(shared), "a_ahead": a_ahead,
            "b_ahead": b_ahead, "ties": ties, "detail": shared,
            "summary": "{} leads {} {}-{}".format(a, b, a_ahead, b_ahead)
            if a_ahead >= b_ahead else "{} leads {} {}-{}".format(b, a, b_ahead, a_ahead)}


# ---------------------------------------------------------------------------
# picking personality
# ---------------------------------------------------------------------------

def pick_personality(name: str) -> dict:
    """How this person picks, measured across every season on record.

    optimism        predicted wins minus actual wins, per season on average.
                    Positive means a homer.
    contrarian_rate share of games where they went against the majority.
    division_faith  how often they picked the Eagles to win an NFC East game.
    """
    seasons = weekly_picks()
    total_games = contrarian = division_games = division_wins = 0
    optimism, accuracy = [], []

    for year, season in seasons.items():
        picks = season["picks"]
        if name not in picks:
            continue
        sheet = picks[name]
        results = season["results"]
        actual_wins = sum(1 for r in results if r == engine.WIN)
        optimism.append(sheet.count(engine.WIN) - actual_wins)
        accuracy.append(sum(1 for i, r in enumerate(results) if sheet[i] == r) / len(results))

        for i in range(len(results)):
            others = [p[i] for n, p in picks.items() if n != name]
            if not others:
                continue
            total_games += 1
            majority = engine.WIN if others.count(engine.WIN) * 2 > len(others) else engine.LOSS
            if sheet[i] != majority:
                contrarian += 1
        for i in season["division_indices"]:
            division_games += 1
            if sheet[i] == engine.WIN:
                division_wins += 1

    if not optimism:
        raise HistoryError("no game-by-game picks on record for {}".format(name))

    return {
        "name": name,
        "seasons_measured": len(optimism),
        "optimism": round(sum(optimism) / len(optimism), 2),
        "most_optimistic_season": max(optimism),
        "accuracy": round(sum(accuracy) / len(accuracy) * 100, 1),
        "contrarian_rate": round(contrarian / total_games * 100, 1) if total_games else None,
        "division_faith": round(division_wins / division_games * 100, 1) if division_games else None,
    }


def field_personalities() -> Dict[str, dict]:
    out = {}
    for name in sorted(career_totals()):
        try:
            out[name] = pick_personality(name)
        except HistoryError:
            continue
    return out


# ---------------------------------------------------------------------------
# context for the newsletter
# ---------------------------------------------------------------------------

def champion_profile() -> dict:
    """What it has historically taken to win."""
    rows = champions()
    scores = [r["winning_score"] for r in rows]
    return {
        "seasons": len(rows),
        "unique_champions": len({r["champion"] for r in rows}),
        "lowest_winning_score": min(scores),
        "lowest_year": rows[scores.index(min(scores))]["year"],
        "highest_winning_score": max(scores),
        "highest_year": rows[scores.index(max(scores))]["year"],
        "average_winning_score": round(sum(scores) / len(scores), 2),
        "average_margin_over_field": round(
            sum(r["winning_score"] - r["field_average"] for r in rows) / len(rows), 2),
        "repeat_champions": sorted(
            {r["champion"] for r in rows
             if sum(1 for x in rows if x["champion"] == r["champion"]) > 1}),
    }


def pace_vs_history(correct: int, games_played: int, total_games: int = 17) -> dict:
    """Is a mid-season pace tracking toward anything historic?"""
    projected = round(correct / games_played * total_games, 1) if games_played else 0.0
    profile = champion_profile()
    beaten = [r for r in champions() if projected >= r["winning_score"]]
    return {
        "correct": correct,
        "games_played": games_played,
        "projected_final": projected,
        "average_winning_score": profile["average_winning_score"],
        "would_have_won_seasons": [r["year"] for r in beaten],
        "would_have_won_count": len(beaten),
        "on_pace_for_record": projected > profile["highest_winning_score"],
        "record_to_beat": profile["highest_winning_score"],
    }


def first_time_since(predicate, label: str = "") -> dict:
    """Most recent season before now where `predicate(season_row)` held.

    predicate receives a champions_by_season row.
    """
    matches = [r for r in champions() if predicate(r)]
    return {
        "label": label,
        "matched_years": [r["year"] for r in matches],
        "most_recent": matches[-1]["year"] if matches else None,
        "count": len(matches),
    }


def context_lines(name: str) -> List[str]:
    """Ready-to-use factual sentences about a competitor. No numbers invented."""
    record = career(name)
    lines = []
    if record["championships"]:
        years = ", ".join(str(y) for y in record["title_years"])
        lines.append("{} has {} title{} ({}).".format(
            name, record["championships"],
            "" if record["championships"] == 1 else "s", years))
    else:
        lines.append("{} has never won the FEP, in {} seasons of trying.".format(
            name, len(record["seasons"])))
    lines.append("Best finish: {} in {}. Worst: {} in {}.".format(
        record["best_finish"], record["best_finish_year"],
        record["worst_finish"], record["worst_finish_year"]))
    lines.append("Career average of {} correct picks a season, {} top-three "
                 "finishes and {} bottom-three.".format(
                     record["average_correct"], record["top3"], record["bottom3"]))
    try:
        personality = pick_personality(name)
        direction = "optimistic" if personality["optimism"] > 0 else "pessimistic"
        lines.append("Picks {} by {} wins a season on average, goes against the "
                     "field {}% of the time, and backs the Eagles in {}% of "
                     "division games.".format(
                         direction, abs(personality["optimism"]),
                         personality["contrarian_rate"], personality["division_faith"]))
    except HistoryError:
        pass
    return lines


# ---------------------------------------------------------------------------
# retro simulation
# ---------------------------------------------------------------------------

def retro_season(year: int, sd_per_game: float = 11.0) -> dict:
    """Replay a past season through the modern model, week by week.

    METHOD, and be explicit about this in any output: historical ESPN win
    probabilities do not exist, so every unplayed game is treated as a coin
    flip. This is the STRAIGHT-UP board, not the weighted one, and it is not
    what the family saw at the time (before 2022 they saw nothing at all).

    Points guesses are also unavailable before 2024, so the third tiebreaker
    cannot be applied and competitors who reach it split evenly.

    What it does faithfully reconstruct: when each competitor was mathematically
    eliminated, when the lead changed, and how close it actually was.
    """
    seasons = weekly_picks()
    if year not in seasons:
        raise HistoryError("no game-by-game picks for {}".format(year))
    season = seasons[year]
    picks, results = season["picks"], season["results"]
    if not picks:
        raise HistoryError("no complete pick sheets for {}".format(year))

    games = len(results)
    weights = [0.5] * games
    guesses = {name: 0 for name in picks}       # identical, so tb3 splits evenly
    divisions = season["division_indices"] or []

    timeline, eliminated, leaders = [], {}, []
    for played in range(games + 1):
        partial = results[:played] + [engine.UNPLAYED] * (games - played)
        board = engine.run(picks, partial, weights, divisions, guesses,
                           points_scored=[None] * games, sd_per_game=sd_per_game,
                           points_model="legacy", skip_validation=True)
        standing = board.ranked()
        leader = standing[0]
        for name in picks:
            if board.weighted[name] <= 0 and name not in eliminated:
                eliminated[name] = played
        timeline.append({
            "games_played": played,
            "week": season["weeks"][played - 1] if played else 0,
            "odds": {n: round(board.weighted[n], 1) for n in board.order},
            "correct": dict(board.current_points),
            "leader": leader,
            "alive": sum(1 for n in board.order if board.weighted[n] > 0),
            "remaining_outcomes": board.remaining_outcomes,
        })
        leaders.append(leader)

    lead_changes = [
        {"after_game": i, "week": season["weeks"][i - 1] if i else 0,
         "from": leaders[i - 1], "to": leaders[i]}
        for i in range(1, len(leaders)) if leaders[i] != leaders[i - 1]
    ]
    final = timeline[-1]
    winner = max(final["correct"], key=lambda n: (final["correct"][n], -ord(n[0])))
    decided = next((t["games_played"] for t in timeline if t["alive"] == 1), games)

    return {
        "year": year,
        "games": games,
        "competitors": sorted(picks),
        "record": "{}-{}".format(results.count(engine.WIN), results.count(engine.LOSS)),
        "timeline": timeline,
        "eliminations": dict(sorted(eliminated.items(), key=lambda kv: kv[1])),
        "lead_changes": lead_changes,
        "leader_by_game": leaders,
        "final_correct": final["correct"],
        "winner_on_picks": winner,
        "decided_after_game": decided,
        "games_to_spare": games - decided,
        "notes": season.get("notes", []),
        "method": ("Straight-up: every unplayed game treated as a coin flip, "
                   "because historical ESPN win probabilities do not exist. "
                   "Points tiebreaker unavailable before 2024, so competitors "
                   "reaching it split evenly."),
    }


def retro_all(years: Optional[Sequence[int]] = None) -> Dict[int, dict]:
    out = {}
    for year in (years or seasons_with_picks()):
        try:
            out[year] = retro_season(year)
        except HistoryError:
            continue
    return out
