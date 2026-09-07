"""Turn a season into the tables the website is built from.

The whole point of this module is that it is pure. A season file goes in, seven
tables come out, nothing is fetched and nothing is written. That matters because
the tables are the contract with Framer, and a contract you can compute in
memory is one you can test exhaustively. The transport (a Google Sheet today,
Framer's Server API later) is somebody else's problem.

THE RULE THIS MODULE EXISTS TO KEEP

    A row published in week N must be identical in week N+1.

Everything here is therefore derived from *recorded facts*, never from a fresh
computation. Standings come out of the weekly snapshots, which are frozen the
moment they are taken, rather than from re-running the engine. So changing the
engine in 2029 cannot move a number the family read in 2026.

The one deliberate exception is `games`, which holds current state: a result
genuinely becomes known partway through the season. Anything that needs the
season *as it stood* in a given week reads `weeks` or `standings` instead, both
of which are per-week and frozen. That distinction is the whole reason `weeks`
exists as its own table.

SLUGS

Every slug carries the year, because Framer upserts on slug. Without the year,
2027 week 1 would land on top of 2026 week 1 and the old row would be gone. The
week is zero padded so that sorting a collection lexically sorts it
chronologically.

There is one column for the season, called `season`, holding the year. It also
serves as the reference to the `seasons` table, whose slug is that year. A
separate numeric `year` column alongside it was two names for one fact and an
invitation to bind a component to the wrong one. `seasons` keeps `year` as its
own attribute, because there it is the thing rather than a pointer to it.

ONE KEY FOR A WEEK

`week_ref` holds `2026-w07` and appears on `games`, `picks` and `standings`. It
is the slug of the matching `weeks` row. That is what lets a single page
variable on the home screen drive three Collection Lists at once: every list
filters on the same field, holding the same string, and one value changes all of
them. Without it the home screen would need a different filter expression per
list, and they would drift.

Colours live only in `competitors`, which is the mapping table. They used to be
denormalised onto every picks and standings row, which meant changing a colour
would have to rewrite hundreds of otherwise frozen rows to take effect. A
component reads them through the `competitor` reference instead.
"""

from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Sequence

from . import chart, engine, history


class Table(NamedTuple):
    name: str
    columns: List[str]
    rows: List[dict]

    def matrix(self) -> List[list]:
        """Header row followed by data rows, ready for a sheet."""
        return [list(self.columns)] + [
            [row.get(column, "") for column in self.columns] for row in self.rows
        ]


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return text or "x"


def split_label(label: str) -> dict:
    """Pull a game label apart into the pieces a component actually wants.

    'vs. Jaguars (London)' is one string doing three jobs: who, where in the
    schedule, and where on earth. ESPN gives it to us joined up, so it gets
    split here rather than in every component that needs just the team name.

        {"opponent": "Jaguars", "home_away": "home",
         "venue": "London", "neutral_site": True}
    """
    venue = ""
    match = re.search(r"\(([^)]*)\)", label)
    if match:
        venue = match.group(1).strip()
    cleaned = re.sub(r"\([^)]*\)", "", label).strip()
    # Not r"(@|at)\b": there is no word boundary between "@" and a space,
    # since neither is a word character, so that pattern never matches "@ Titans".
    away = bool(re.match(r"^\s*(@|at\s)", cleaned, flags=re.I))
    opponent = re.sub(r"^\s*(vs\.?|@|at)\s*", "", cleaned, flags=re.I).strip()
    return {"opponent": opponent,
            "home_away": "away" if away else "home",
            "venue": venue,
            "neutral_site": bool(venue)}


def _opponent_slug(label: str) -> str:
    """'vs. Jaguars (London)' -> 'jaguars'. Just the team."""
    return _slugify(split_label(label)["opponent"])


def _blank(value):
    """None becomes an empty cell, not the string 'None'."""
    return "" if value is None else value


# ---------------------------------------------------------------------------
# helpers over the season file
# ---------------------------------------------------------------------------

def _submitted(season: dict) -> List[str]:
    """Roster members who have actually handed in a pick sheet."""
    return [name for name in season["roster"] if season["picks"].get(name)]


def _snapshots(season: dict) -> Dict[int, dict]:
    return {s["week"]: s for s in season.get("snapshots", [])}


def _bye_weeks(season: dict) -> List[int]:
    weeks = season.get("bye_weeks")
    if weeks:
        return list(weeks)
    single = season.get("bye_week")
    return [single] if single else []


def _record(season: dict) -> dict:
    results = [g["result"] for g in season["games"]]
    return {
        "wins": results.count(engine.WIN),
        "losses": results.count(engine.LOSS),
        "ties": results.count(engine.TIE),
        "played": sum(1 for r in results if r != engine.UNPLAYED),
        "points": sum(g["points_for"] or 0 for g in season["games"]),
    }


def _status(season: dict) -> str:
    record = _record(season)
    if record["played"] == 0:
        return "upcoming"
    if record["played"] == len(season["games"]):
        return "final"
    return "in_progress"


def _ranked(board: Dict[str, float]) -> Dict[str, int]:
    """Standard competition ranking, so a tie shares a place."""
    order = sorted(board, key=lambda n: (-board[n], n))
    ranks, previous, place = {}, None, 0
    for position, name in enumerate(order, start=1):
        if board[name] != previous:
            place = position
            previous = board[name]
        ranks[name] = place
    return ranks


def _career(name: str) -> dict:
    """Career record, or a rookie's empty one.

    history.career() raises for a name it has never seen, which is exactly what
    happens the first year somebody joins. A newcomer is not an error.
    """
    try:
        return history.career(name)
    except history.HistoryError:
        return {"seasons": [], "first_season": None, "championships": 0,
                "title_years": [], "career_points": 0, "all_time_place": None,
                "average_place": None, "average_correct": None}


# ---------------------------------------------------------------------------
# the tables
# ---------------------------------------------------------------------------

SEASON_COLUMNS = [
    "slug", "year", "status", "current_week", "games_total", "bye_weeks",
    "roster_size", "eagles_wins", "eagles_losses", "eagles_ties",
    "eagles_points", "champion", "champion_correct", "field_average",
]


def seasons_table(season: dict, current_week: Optional[int] = None) -> Table:
    year = season["year"]
    record = _record(season)
    snapshots = _snapshots(season)
    if current_week is None:
        current_week = max(snapshots) if snapshots else 0

    champion, champion_correct, field_average = "", "", ""
    if _status(season) == "final" and snapshots:
        final = snapshots[max(snapshots)]
        correct = final.get("current_points") or {}
        if correct:
            best = max(correct.values())
            # The champion is whoever the final board actually settled on, not
            # simply the top pick count, because the tiebreakers decide it.
            leader = max(final["weighted"], key=lambda n: (final["weighted"][n], n))
            champion, champion_correct = leader, best
            field_average = round(sum(correct.values()) / len(correct), 1)

    return Table("seasons", SEASON_COLUMNS, [{
        "slug": str(year),
        "year": year,
        "status": _status(season),
        "current_week": current_week,
        "games_total": len(season["games"]),
        "bye_weeks": ", ".join(str(w) for w in _bye_weeks(season)),
        "roster_size": len(season["roster"]),
        "eagles_wins": record["wins"],
        "eagles_losses": record["losses"],
        "eagles_ties": record["ties"],
        "eagles_points": record["points"],
        "champion": champion,
        "champion_correct": champion_correct,
        "field_average": field_average,
    }])


COMPETITOR_COLUMNS = [
    "slug", "name", "color", "first_season", "seasons_played", "titles",
    "title_years", "career_points", "all_time_rank",
]


def competitors_table(season: dict) -> Table:
    colors = season.get("colors") or chart.colors_for(season["roster"])
    rows = []
    for name in season["roster"]:
        record = _career(name)
        seasons = record["seasons"]
        rows.append({
            "slug": _slugify(name),
            "name": name,
            "color": colors.get(name, ""),
            # A rookie's first season is this one, which history cannot know.
            "first_season": record["first_season"] or season["year"],
            "seasons_played": len(seasons) + (0 if season["year"] in seasons else 1),
            "titles": record["championships"],
            "title_years": ", ".join(str(y) for y in record["title_years"]),
            "career_points": record["career_points"],
            "all_time_rank": _blank(record["all_time_place"]),
        })
    return Table("competitors", COMPETITOR_COLUMNS, rows)


COMPETITOR_SEASON_COLUMNS = [
    "slug", "season", "competitor", "name",
    "predicted_wins", "predicted_losses", "predicted_division_wins",
    "predicted_division_losses", "points_guess", "correct", "place",
    "eliminated_week", "is_champion",
]


def competitor_seasons_table(season: dict) -> Table:
    year = season["year"]
    snapshots = _snapshots(season)
    latest = snapshots[max(snapshots)] if snapshots else None
    division = season["division_indices"]
    games = len(season["games"])
    final = _status(season) == "final"

    ranks = _ranked(latest["weighted"]) if latest else {}
    rows = []
    for name in _submitted(season):
        sheet = season["picks"][name]
        wins = sheet.count(engine.WIN)
        division_wins = sum(1 for i in division if sheet[i] == engine.WIN)
        eliminated = ""
        for week in sorted(snapshots):
            if snapshots[week]["weighted"].get(name, 0) == 0:
                eliminated = week
                break
        rows.append({
            "slug": "{}-{}".format(year, _slugify(name)),
            "season": str(year),
            "competitor": _slugify(name),
            "name": name,
            "predicted_wins": wins,
            "predicted_losses": games - wins,
            "predicted_division_wins": division_wins,
            "predicted_division_losses": len(division) - division_wins,
            "points_guess": _blank(season["points_guess"].get(name)),
            "correct": latest["current_points"].get(name, "") if latest else "",
            "place": ranks.get(name, ""),
            "eliminated_week": eliminated,
            "is_champion": bool(final and ranks.get(name) == 1),
        })
    return Table("competitor_seasons", COMPETITOR_SEASON_COLUMNS, rows)


GAME_COLUMNS = [
    "slug", "season", "week_ref", "nfl_week", "game_index", "label", "opponent",
    "home_away", "venue", "neutral_site", "is_division", "kickoff", "result",
    "eagles_points", "opponent_points", "espn_weight",
]


def games_table(season: dict) -> Table:
    """Current state, deliberately. A result becomes known during the season.

    Nothing that needs a frozen view of the past should read this table; that is
    what `weeks` and `standings` are for.
    """
    year = season["year"]
    rows = []
    for game in season["games"]:
        label = game["label"]
        parts = split_label(label)
        rows.append({
            "slug": "{}-w{:02d}-{}".format(year, game["nfl_week"],
                                           _opponent_slug(label)),
            "season": str(year),
            "week_ref": "{}-w{:02d}".format(year, game["nfl_week"]),
            "nfl_week": game["nfl_week"],
            "game_index": game["index"],
            "label": label,
            "opponent": parts["opponent"],
            "home_away": parts["home_away"],
            "venue": parts["venue"],
            "neutral_site": parts["neutral_site"],
            "is_division": bool(game["division"]),
            "kickoff": _blank(game.get("date")),
            "result": "" if game["result"] == engine.UNPLAYED else game["result"],
            "eagles_points": _blank(game.get("points_for")),
            "opponent_points": _blank(game.get("points_against")),
            "espn_weight": _blank(game.get("weight")),
        })
    return Table("games", GAME_COLUMNS, rows)


WEEK_COLUMNS = [
    "slug", "season", "week", "label", "is_bye", "game", "game_label", "result",
    "eagles_record", "leader", "leader_pct", "remaining_outcomes",
    "still_alive", "decided_outright",
]


def weeks_table(season: dict) -> Table:
    """One frozen row per week, built from that week's snapshot.

    This is what a newsletter page reads for "the season as it stood then". The
    snapshot carries its own copy of the results, so a week's record cannot be
    contaminated by a game played afterwards.
    """
    year = season["year"]
    byes = set(_bye_weeks(season))
    by_week = {g["nfl_week"]: g for g in season["games"]}
    rows = []
    for snapshot in sorted(season.get("snapshots", []), key=lambda s: s["week"]):
        week = snapshot["week"]
        results = snapshot.get("results") or []
        game = by_week.get(week)
        played = [r for r in results if r != engine.UNPLAYED]
        board = snapshot["weighted"]
        leader = max(board, key=lambda n: (board[n], n)) if board else ""

        result = ""
        if game and game["index"] < len(results):
            frozen = results[game["index"]]
            result = "" if frozen == engine.UNPLAYED else frozen

        rows.append({
            "slug": "{}-w{:02d}".format(year, week),
            "season": str(year),
            "week": week,
            "label": "Preseason" if week == 0 else "Week {}".format(week),
            "is_bye": week in byes,
            "game": ("{}-w{:02d}-{}".format(year, week, _opponent_slug(game["label"]))
                     if game else ""),
            "game_label": game["label"] if game else ("Bye" if week in byes else ""),
            "result": result,
            "eagles_record": "{}-{}".format(played.count(engine.WIN),
                                            played.count(engine.LOSS)),
            "leader": leader,
            "leader_pct": board.get(leader, "") if leader else "",
            "remaining_outcomes": snapshot.get("remaining_outcomes", ""),
            "still_alive": sum(1 for v in board.values() if v > 0),
            "decided_outright": round(
                (snapshot.get("deciding") or {}).get("outright", 0), 1),
        })
    return Table("weeks", WEEK_COLUMNS, rows)


PICK_COLUMNS = [
    "slug", "season", "week_ref", "nfl_week", "game", "competitor", "name",
    "pick",
]


def picks_table(season: dict) -> Table:
    """Written once a season and never again.

    There is deliberately no `correct` column. It would have to be rewritten
    every week as results land, which would turn a write-once table into a
    weekly one for no gain: a component can compare `pick` against the linked
    game's `result` itself.
    """
    year = season["year"]
    rows = []
    for name in _submitted(season):
        sheet = season["picks"][name]
        for game in season["games"]:
            game_slug = "{}-w{:02d}-{}".format(year, game["nfl_week"],
                                               _opponent_slug(game["label"]))
            rows.append({
                "slug": "{}-{}".format(game_slug, _slugify(name)),
                "season": str(year),
                "week_ref": "{}-w{:02d}".format(year, game["nfl_week"]),
                "nfl_week": game["nfl_week"],
                "game": game_slug,
                "competitor": _slugify(name),
                "name": name,
                "pick": sheet[game["index"]],
            })
    return Table("picks", PICK_COLUMNS, rows)


STANDING_COLUMNS = [
    "slug", "season", "week", "week_ref", "competitor", "name",
    "weighted", "straight", "correct", "rank", "change", "is_eliminated",
    "is_bye",
]


def standings_table(season: dict) -> Table:
    """One row per competitor per week, straight out of the frozen snapshots.

    Rank and change are computed from the snapshot alone (rank within its own
    board, change against the previous snapshot), so both are functions of data
    that can no longer move.
    """
    year = season["year"]
    byes = set(_bye_weeks(season))
    ordered = sorted(season.get("snapshots", []), key=lambda s: s["week"])

    rows, previous = [], {}
    for snapshot in ordered:
        week = snapshot["week"]
        board = snapshot["weighted"]
        ranks = _ranked(board)
        for name in sorted(board):
            before = previous.get(name)
            rows.append({
                "slug": "{}-w{:02d}-{}".format(year, week, _slugify(name)),
                "season": str(year),
                "week": week,
                "week_ref": "{}-w{:02d}".format(year, week),
                "competitor": _slugify(name),
                "name": name,
                "weighted": board[name],
                "straight": snapshot.get("straight", {}).get(name, ""),
                "correct": snapshot.get("current_points", {}).get(name, ""),
                "rank": ranks[name],
                "change": "" if before is None else round(board[name] - before, 1),
                "is_eliminated": board[name] == 0,
                "is_bye": week in byes,
            })
        previous = dict(board)
    return Table("standings", STANDING_COLUMNS, rows)


# ---------------------------------------------------------------------------

BUILDERS = [
    seasons_table, competitors_table, competitor_seasons_table,
    games_table, weeks_table, picks_table, standings_table,
]


def tables(season: dict) -> Dict[str, Table]:
    """Every table, keyed by name."""
    built = {}
    for builder in BUILDERS:
        table = builder(season)
        built[table.name] = table
    return built
