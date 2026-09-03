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

from . import engine, espn

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
        "points_guess": {name: None for name in roster},
        "games": games,
        "division_indices": pulled["division_indices"],
        "week_to_game_index": {str(k): v for k, v in pulled["week_to_game_index"].items()},
        "bye_week": pulled["bye_week"],
        "snapshots": [],
        "sheet": dict(DEFAULT_SHEET),
        "model": dict(DEFAULT_MODEL),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load(year: int) -> dict:
    with open(path_for(year)) as fh:
        return json.load(fh)


def save(season: dict) -> str:
    season["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(DATA_DIR, exist_ok=True)
    destination = path_for(season["year"])
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

def snapshot(season: dict, week: int, board: engine.Board, note: str = "") -> dict:
    """Record the board for a week. Re-saving the same week replaces it."""
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
        "results": results(season),
        "weights": weights(season),
    }
    season["snapshots"] = [s for s in season.get("snapshots", []) if s["week"] != week]
    season["snapshots"].append(entry)
    season["snapshots"].sort(key=lambda s: s["week"])
    return entry


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
