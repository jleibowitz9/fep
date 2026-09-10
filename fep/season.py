"""
The season file: the single source of truth for a FEP season.

Everything the pool needs lives in one JSON document under data/. It holds
FACTS only:

    who is playing, what they picked, what they guessed for points,
    what the schedule is, what has actually happened, what ESPN thinks,
    and one snapshot of the board per week.

It deliberately does NOT hold derived statistics. Leverage, heat check,
deciding-layer splits and the rest are all recomputed on demand from these
facts, because the engine is fast enough that storing them would only create a
second copy that goes stale the moment a result is corrected.

A weekly snapshot IS a fact, though: it is what the family saw at the time, and
the Heat Check segment is defined as the change from it.

PROVENANCE
----------
Every result, score and weight records where it came from ("espn" or "manual").
Refreshing from ESPN never overwrites a manual override. That is what makes it
safe to hit Refresh whenever you like.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from . import chart, engine, espn

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# The Google Sheet's column order. This is the external contract with Framer,
# so the roster is stored in this order and never re-sorted.
DEFAULT_ROSTER = [
    "Amir", "Andy", "Buhduh", "Emer", "Hanan", "Jacob",
    "Jay", "Jen", "Marsha", "Nathan", "Pop", "Sarah",
]

DEFAULT_SHEET = {
    "spreadsheet_id": None,
    "tab": None,
    # The straight-up board's tab, if Framer reads one. Null means only the
    # weighted board is written.
    "straight_tab": None,
    # Row 1 is the header, row 2 is week 0, row 20 is week 18.
    # Column A holds the week labels and columns N onward hold Jacob's placement
    # formulas. NEITHER may ever be written.
    "range": "B2:M20",
    "first_data_row": 2,
    "first_week": 0,
    "last_week": 18,
}

DEFAULT_MODEL = {
    "sd_per_game": engine.DEFAULT_SD_PER_GAME,
    "prior_ppg": engine.DEFAULT_PRIOR_PPG,
    "prior_weight_games": engine.DEFAULT_PRIOR_WEIGHT_GAMES,
    "points_model": "shrunk",
}


def path_for(year: int) -> str:
    return os.path.join(DATA_DIR, "season_{}.json".format(year))


# ---------------------------------------------------------------------------
# create / load / save
# ---------------------------------------------------------------------------

def create(year: int, roster: Optional[List[str]] = None, refresh: bool = True) -> dict:
    """Build a fresh season document from the ESPN schedule."""
    roster = list(roster or DEFAULT_ROSTER)
    pulled = espn.fetch_season(year, refresh=refresh)

    games = []
    for game in pulled["games"]:
        games.append(
            {
                "index": game["index"],
                "nfl_week": game["nfl_week"],
                "event_id": game["event_id"],
                "opponent": game["opponent"],
                "label": game["label"],
                "home": game["home"],
                "neutral_site": game.get("neutral_site", False),
                "venue": game.get("venue"),
                "date": game["date"],
                "division": game["division"],
                "result": game["result"],
                "result_source": "espn",
                "points_for": game["points_for"],
                "points_against": game["points_against"],
                "points_source": "espn",
                "weight": game.get("weight"),
                "weight_source": "espn",
            }
        )

    return {
        "year": year,
        "roster": roster,
        "picks": {name: [] for name in roster},
        # Recorded, not derived. A competitor's colour is part of their
        # identity, so it is written down the first time they appear and never
        # recomputed from roster position afterwards.
        "colors": chart.colors_for(roster),
        "points_guess": {name: None for name in roster},
        "games": games,
        "division_indices": pulled["division_indices"],
        "week_to_game_index": {str(k): v for k, v in pulled["week_to_game_index"].items()},
        "bye_week": pulled["bye_week"],
        "bye_weeks": pulled.get("bye_weeks", []),
        "snapshots": [],
        "sheet": dict(DEFAULT_SHEET),
        "model": dict(DEFAULT_MODEL),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load(year: int) -> dict:
    with open(path_for(year)) as fh:
        return json.load(fh)


# When the season was last written and when ESPN was last asked. Both describe
# the act of recording rather than anything about the season, so a save whose
# only difference is one of these is not a save at all.
BOOKKEEPING_FIELDS = ("updated_at", "last_refresh", "last_refresh_changes")


def _body(season: dict) -> str:
    """The season as it will be stored, minus the bookkeeping."""
    return json.dumps({k: v for k, v in season.items()
                       if k not in BOOKKEEPING_FIELDS},
                      indent=2, sort_keys=True)


def save(season: dict) -> str:
    """Write the season file, unless writing it would say nothing new.

    A run that changed nothing used to still rewrite `updated_at` and
    `last_refresh`, and since the backup stages the whole `data` directory that
    produced a commit claiming a weekly run had happened. Six of them are in
    this repository's history. The snapshot guard alone does not fix it: the
    snapshot stays put and the timestamps move anyway.

    So the comparison ignores the bookkeeping. `last_refresh` therefore advances
    only when the refresh actually brought something back, which is the more
    useful fact of the two -- "when did this season last learn anything" rather
    than "when did someone last ask".
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    destination = path_for(season["year"])

    if os.path.exists(destination):
        try:
            with open(destination) as fh:
                if _body(json.load(fh)) == _body(season):
                    return destination      # nothing to say
        except (ValueError, OSError):
            pass                            # unreadable: write over it

    season["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = destination + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(season, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, destination)
    return destination


def load_or_create(year: int, roster: Optional[List[str]] = None) -> dict:
    try:
        return load(year)
    except FileNotFoundError:
        season = create(year, roster=roster)
        save(season)
        return season


# ---------------------------------------------------------------------------
# refreshing from ESPN without clobbering manual edits
# ---------------------------------------------------------------------------

def refresh(season: dict, force: bool = True) -> dict:
    """Pull the latest results, scores and weights, preserving overrides.

    A field whose *_source is "manual" is never touched. Everything else is
    updated in place.
    """
    pulled = espn.fetch_season(season["year"], refresh=force)
    by_index = {g["index"]: g for g in pulled["games"]}

    changes = []
    for game in season["games"]:
        fresh = by_index.get(game["index"])
        if fresh is None:
            continue

        # Schedule metadata is always ESPN's; it is not something to override.
        for field in ("label", "opponent", "date", "nfl_week", "home",
                      "neutral_site", "venue", "division", "event_id"):
            if field in fresh:
                game[field] = fresh[field]

        if game.get("result_source") != "manual" and fresh["result"] != game.get("result"):
            changes.append("game {} result {} -> {}".format(
                game["index"], game.get("result"), fresh["result"]))
            game["result"] = fresh["result"]

        if game.get("points_source") != "manual":
            if fresh["points_for"] != game.get("points_for"):
                changes.append("game {} points {} -> {}".format(
                    game["index"], game.get("points_for"), fresh["points_for"]))
            game["points_for"] = fresh["points_for"]
            game["points_against"] = fresh["points_against"]

        if game.get("weight_source") != "manual" and fresh.get("weight") is not None:
            old_weight = game.get("weight")
            if old_weight != fresh["weight"]:
                changes.append("game {} weight {} -> {}".format(
                    game["index"], old_weight, fresh["weight"]))
            game["weight"] = fresh["weight"]

    season["division_indices"] = pulled["division_indices"]
    season["week_to_game_index"] = {str(k): v for k, v in pulled["week_to_game_index"].items()}
    season["bye_week"] = pulled["bye_week"]
    season["bye_weeks"] = pulled.get("bye_weeks", [])
    season["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    season["last_refresh_changes"] = changes
    return season


def set_override(season: dict, index: int, field: str, value) -> dict:
    """Manually pin a result, weight or score, and mark it so ESPN cannot undo it."""
    field_to_source = {"result": "result_source", "weight": "weight_source",
                       "points_for": "points_source"}
    if field not in field_to_source:
        raise ValueError("cannot override {}".format(field))
    for game in season["games"]:
        if game["index"] == index:
            game[field] = value
            game[field_to_source[field]] = "manual"
            return season
    raise KeyError("no game at index {}".format(index))


def clear_override(season: dict, index: int, field: str) -> dict:
    field_to_source = {"result": "result_source", "weight": "weight_source",
                       "points_for": "points_source"}
    for game in season["games"]:
        if game["index"] == index:
            game[field_to_source[field]] = "espn"
            return season
    raise KeyError("no game at index {}".format(index))


# ---------------------------------------------------------------------------
# views onto the season
# ---------------------------------------------------------------------------

def results(season: dict) -> List[str]:
    return [g["result"] for g in season["games"]]


def weights(season: dict) -> List[Optional[float]]:
    return [g["weight"] for g in season["games"]]


def points_scored(season: dict) -> List[Optional[int]]:
    return [g["points_for"] for g in season["games"]]


def labels(season: dict) -> List[str]:
    return [g["label"] for g in season["games"]]


def games_played(season: dict) -> int:
    return sum(1 for g in season["games"] if g["result"] != engine.UNPLAYED)


def current_nfl_week(season: dict) -> int:
    """The NFL week the season is currently 'at'.

    This is the highest week whose game has a result, which after the bye is NOT
    the same as the number of games played. Returns 0 before anything is played.
    """
    played = {g["nfl_week"] for g in season["games"] if g["result"] != engine.UNPLAYED}
    return max(played) if played else 0


def week_dates(season: dict) -> Dict[int, str]:
    """The date each week is reached, as ISO strings.

    A week with a game is dated by that game. A bye has no game and therefore
    no date of its own, so it takes the previous week's plus seven days. That
    is what makes a bye a week the calendar lands on at all, rather than one it
    steps over.
    """
    import datetime

    by_week = {g["nfl_week"]: g.get("date") for g in season["games"]}
    sheet = season.get("sheet", DEFAULT_SHEET)
    last = sheet.get("last_week", 18)

    dates: Dict[int, str] = {}
    previous = None
    for week in range(1, last + 1):
        date = by_week.get(week)
        if date is None and previous is not None:
            date = (datetime.date.fromisoformat(previous)
                    + datetime.timedelta(days=7)).isoformat()
        if date is None:
            continue  # nothing before it to count from yet
        dates[week] = date
        previous = date
    return dates


def week_to_run(season: dict, today: Optional[str] = None) -> int:
    """The week the weekly run should record, read off the calendar.

    `current_nfl_week` answers a different question -- the last week that
    produced a result -- and during a bye the two diverge. Week 10 never holds
    a result, so a run defaulting to the scoreboard re-runs week 9 and leaves
    week 10 with no snapshot, no chart and no row on the Sheet. The schedule
    knows where the season is even when the scoreboard does not.

    ISO dates compare correctly as strings, so nothing here has to be parsed.
    """
    today = today or time.strftime("%Y-%m-%d")
    sheet = season.get("sheet", DEFAULT_SHEET)
    reached = [w for w, date in week_dates(season).items() if date <= today]
    if not reached:
        return sheet.get("first_week", 0)  # preseason: the week 0 board
    return min(max(reached), sheet.get("last_week", 18))


def game_index_for_week(season: dict, week: int) -> Optional[int]:
    """Game index for an NFL week, or None if that week is the bye."""
    return season.get("week_to_game_index", {}).get(str(week))


def is_bye_week(season: dict, week: int) -> bool:
    mapping = season.get("week_to_game_index", {})
    return str(week) in mapping and mapping[str(week)] is None


def board_weeks(season: dict) -> List[int]:
    """Every week that gets a board row, week 0 (preseason) through the finale."""
    sheet = season.get("sheet", DEFAULT_SHEET)
    return list(range(sheet.get("first_week", 0), sheet.get("last_week", 18) + 1))


def has_picks(season: dict) -> bool:
    games = len(season["games"])
    return bool(season["picks"]) and all(
        len(sheet) == games for sheet in season["picks"].values()
    )


# ---------------------------------------------------------------------------
# running the model
# ---------------------------------------------------------------------------

def results_through_week(season: dict, week: int) -> List[str]:
    """Results as they stood at the end of an NFL week.

    Anything played later is masked back to unplayed. This matters because the
    newsletter is often written a few days late, by which point ESPN may already
    have a Thursday result from the following week. Without this, a "Week 12"
    board would quietly include a Week 13 game, and the snapshot the family sees
    would not be the board that actually existed that week.
    """
    return [
        g["result"] if g["nfl_week"] <= week else engine.UNPLAYED
        for g in season["games"]
    ]


def points_through_week(season: dict, week: int) -> List[Optional[int]]:
    return [
        g["points_for"] if g["nfl_week"] <= week else None
        for g in season["games"]
    ]


def run(season: dict, results_override: Optional[List[str]] = None,
        through_week: Optional[int] = None, **kwargs) -> engine.Board:
    """Run the engine against the season's current state.

    through_week pins the board to how it stood at the end of that NFL week.
    """
    model = dict(DEFAULT_MODEL)
    model.update(season.get("model") or {})
    model.update(kwargs)

    if results_override is not None:
        current, scored = results_override, points_scored(season)
    elif through_week is not None:
        current = results_through_week(season, through_week)
        scored = points_through_week(season, through_week)
    else:
        current, scored = results(season), points_scored(season)

    return engine.run(
        picks=season["picks"],
        results=current,
        weights=weights(season),
        division_indices=season["division_indices"],
        points_guess=season["points_guess"],
        points_scored=scored,
        **model
    )


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------

def _opponent_name(label: str) -> str:
    """"@ Vikings" -> "Vikings". The season file stores ESPN's abbreviation."""
    import re
    cleaned = re.sub(r"\([^)]*\)", "", label)
    return re.sub(r"^\s*(vs\.?|@|at)\s*", "", cleaned, flags=re.I).strip()


def _game_facts(season: dict, week: int) -> Optional[dict]:
    """What was known about this week's game, copied into the snapshot."""
    for game in season["games"]:
        if game["nfl_week"] != week:
            continue
        return {
            "index": game["index"],
            "event_id": game.get("event_id"),
            "label": game["label"],
            "opponent": game.get("opponent"),
            "opponent_name": _opponent_name(game["label"]),
            "home": game.get("home"),
            "neutral_site": game.get("neutral_site"),
            "venue": game.get("venue"),
            "division": game.get("division"),
            "result": game["result"],
            "points_for": game.get("points_for"),
            "points_against": game.get("points_against"),
        }
    return None


# The fields of a snapshot that ARE the record. Everything else -- when it was
# taken, the note attached to it, the audit trail of corrections -- describes
# the recording rather than what was recorded, and can differ between two runs
# that saw exactly the same season. Comparing on these is what lets an
# identical replay be recognised as identical.
SNAPSHOT_RECORD_FIELDS = (
    "week", "is_bye", "remaining_outcomes", "weighted", "straight",
    "current_points", "deciding", "points_mean", "points_sd",
    "results", "points_for", "weights", "eliminated", "game",
)


def _flatten(value, prefix=""):
    """Every leaf of a nested snapshot field, named by its path."""
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(value[key],
                                "{}.{}".format(prefix, key) if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, "{}[{}]".format(prefix, index))
    else:
        yield prefix, value


def snapshot_drift(stored: dict, incoming: dict, limit: int = 4) -> List[str]:
    """What moved between two recordings of the same week.

    Named paths rather than a diff of the whole entry, so a refusal can say
    `weighted.Amir: 12.3 -> 11.8` and be acted on. Deliberately the same shape
    as `describeDrift` in appsscript/Code.gs: the two halves of this system
    enforce the same contract and should describe a breach the same way.
    """
    parts, extra = [], 0
    for field in SNAPSHOT_RECORD_FIELDS:
        was = dict(_flatten(stored.get(field), field))
        now = dict(_flatten(incoming.get(field), field))
        for key in sorted(set(was) | set(now)):
            if was.get(key) == now.get(key):
                continue
            if len(parts) < limit:
                parts.append("{}: {!r} -> {!r}".format(key, was.get(key), now.get(key)))
            else:
                extra += 1
    if extra:
        parts.append("and {} more".format(extra))
    return parts


def snapshot(season: dict, week: int, board: engine.Board, note: str = "",
             correction: Optional[str] = None):
    """Record the board for a week. A week already recorded does not move.

    Returns `(entry, status)`, where status is one of:

        created     the week had no snapshot and now has one
        unchanged   an identical replay: nothing was written, not even the
                    timestamp, and the stored entry comes back untouched
        corrected   a deliberate, audited rewrite

    THE WEEK IS THE RECORD
    ----------------------
    A snapshot is what the family saw that week, and the Heat Check is defined
    as the change from it, so a week that quietly re-records itself changes
    history that has already been published. This used to be exactly what
    happened: re-running a week deleted the stored entry and replaced it, and a
    single moved weight anywhere in the season silently rewrote all twelve
    probabilities in a week that had already gone out.

    So a replay is compared against what is stored. Identical, and it is a
    no-op -- which is also what stops a re-run from producing a commit that
    only moves `taken_at`. Different, and it is refused by name unless the
    caller passes `correction`, in which case the change is made AND recorded
    on the entry, because a correction that leaves no trace is just drift with
    better manners.

    This is deliberately the same contract `FROZEN_TABS` enforces in
    appsscript/Code.gs. A guard that only exists on one side of the wire is not
    a guard.

    The results and points stored here are masked to that week, not copied from
    the season's current state. When a week is run live the two are the same,
    but they are not when a week is re-run or backfilled later, and in that case
    copying the current state would write games from the future into a past
    week's record. Anything reading a snapshot is reading what was true then.

    Weights are the exception and cannot be: ESPN only publishes the current
    line, so a backfilled week carries today's weights rather than that week's.
    That is exactly why they are snapshotted at all, and it is why the weekly
    run should happen weekly.
    """
    entry = {
        "week": week,
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "is_bye": is_bye_week(season, week),
        "remaining_outcomes": board.remaining_outcomes,
        "weighted": {n: round(board.weighted[n], 1) for n in board.order},
        "straight": {n: round(board.straight[n], 1) for n in board.order},
        "current_points": dict(board.current_points),
        "deciding": {k: round(v, 1) for k, v in board.deciding.items()},
        "points_mean": round(board.points["mean"], 1),
        "points_sd": round(board.points["sd"], 1),
        "results": results_through_week(season, week),
        "points_for": points_through_week(season, week),
        "weights": weights(season),
        # Who is mathematically out, from the unrounded board.
        #
        # The stored percentages are rounded to one decimal, so a competitor
        # clinging on at 0.04% shows as 0.0 and is indistinguishable from one
        # who is actually finished. Reading elimination off the displayed
        # number therefore buried people who were still alive.
        "eliminated": sorted(n for n in board.order if board.weighted[n] == 0.0),
        # The week's own matchup, frozen here rather than looked up later.
        # A label or a venue can be corrected in ESPN's data at any time, and a
        # historical row that reads today's schedule would change with it.
        "game": _game_facts(season, week),
    }
    stored = get_snapshot(season, week)
    if stored is not None:
        drift = snapshot_drift(stored, entry)
        if not drift:
            # Nothing to write. Returning the stored entry rather than the new
            # one keeps the original `taken_at`, which is the honest answer to
            # "when was this week recorded".
            return stored, "unchanged"
        if not correction:
            raise engine.SeasonError(
                "week {} is already recorded and this run does not match it:\n"
                "  {}\n"
                "  A snapshot is what the family saw that week. If this is a\n"
                "  genuine correction, say so and it will be recorded:\n"
                "    python3 cli.py week {} --correction \"why\"".format(
                    week, "\n  ".join(drift), week))
        entry["corrections"] = list(stored.get("corrections") or []) + [{
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "reason": correction,
            "changed": drift,
        }]
        status = "corrected"
    else:
        status = "created"

    season["snapshots"] = [s for s in season.get("snapshots", []) if s["week"] != week]
    season["snapshots"].append(entry)
    season["snapshots"].sort(key=lambda s: s["week"])
    return entry, status


def get_snapshot(season: dict, week: int) -> Optional[dict]:
    for entry in season.get("snapshots", []):
        if entry["week"] == week:
            return entry
    return None


def previous_snapshot(season: dict, week: int) -> Optional[dict]:
    earlier = [s for s in season.get("snapshots", []) if s["week"] < week]
    return earlier[-1] if earlier else None


def snapshot_matrix(season: dict) -> Dict[int, Dict[str, float]]:
    """{week: {name: weighted %}} for every snapshot taken. The chart series."""
    return {s["week"]: s["weighted"] for s in season.get("snapshots", [])}
