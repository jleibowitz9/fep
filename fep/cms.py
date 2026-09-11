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

The deliberate exceptions are `games` and, in one column, `picks`: a result
genuinely becomes known partway through the season, and `picks.correct` is that
same fact seen from the other side. Both only ever move from blank to settled,
never from one answer to another. The `decided_*` columns on `weeks` were
appended in September 2026 and filled in once from the stored `deciding` of
rows already published; that is the same blank-to-settled move, done once. Anything that needs the season *as it stood*
in a given week reads `weeks` or `standings` instead, both of which are per-week
and frozen. That distinction is the whole reason `weeks` exists as its own
table.

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


def game_slug(year: int, nfl_week: int) -> str:
    """A game's permanent id: the season and the week it was played in.

    It used to carry the opponent, which read nicely and was wrong. A slug is an
    identity, and identity must not be derived from a value that can be edited.
    Correcting one team name in ESPN's data changed the slug, so the corrected
    row was published as a *new* row and the original was left behind forever,
    because the transport never deletes.

    Season and week cannot be corrected: they are what defines the game.
    """
    return "{}-w{:02d}".format(year, nfl_week)


def game_facts(season: dict, game: dict) -> dict:
    """The structured fields, preferring what ESPN gave us over parsing.

    The season file already carries opponent, home, neutral_site, venue and
    event_id per game. Re-deriving them from the display label was not only
    redundant, it disagreed: the London game is `home: false` with venue
    "Tottenham Hotspur Stadium" in the data, and the label parser called it a
    home game in "London". Parsing is kept only for a game that predates those
    fields.
    """
    parsed = split_label(game["label"])
    home = game.get("home")
    return {
        # The label is the better source for the *name*: the season file's
        # `opponent` is ESPN's abbreviation ("MIN"), which is not what a page
        # wants to show. It is kept alongside as opponent_abbr, since it is the
        # stable identifier of the team.
        "opponent": parsed["opponent"] or game.get("opponent") or "",
        "opponent_abbr": game.get("opponent") or "",
        # Everything else, the recorded fields win. The label says "vs." for a
        # neutral-site game, and its parenthetical is a city where the data has
        # the actual stadium.
        "home_away": ("home" if home else "away") if home is not None
                     else parsed["home_away"],
        "venue": game.get("venue") or parsed["venue"],
        "neutral_site": bool(game.get("neutral_site", parsed["neutral_site"])),
        "event_id": game.get("event_id") or "",
    }


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
    """A season is only final once the final board exists.

    Every game being played is not enough. The board that decides it is a
    separate artefact, and until it has been run and snapshotted there is no
    champion to name. Deciding otherwise published the leader of whatever the
    most recent board happened to be, which on a completed schedule whose last
    snapshot was week 16 meant crowning the wrong person.
    """
    record = _record(season)
    if record["played"] == 0:
        return "upcoming"
    if record["played"] != len(season["games"]):
        return "in_progress"
    return "final" if _final_snapshot(season) else "in_progress"


def _final_snapshot(season: dict) -> Optional[dict]:
    """The snapshot that settles the season, or None if it has not been taken.

    It must cover the last scheduled week and leave a single possible outcome:
    a board with anything still undecided has not settled anything.
    """
    snapshots = season.get("snapshots") or []
    if not snapshots:
        return None
    weeks = [g["nfl_week"] for g in season["games"]]
    if not weeks:
        return None
    latest = max(snapshots, key=lambda s: s["week"])
    if latest["week"] < max(weeks):
        return None
    if latest.get("remaining_outcomes", 0) != 1:
        return None
    return latest


def _champions(snapshot: dict) -> List[str]:
    """Everyone the settling board puts first. Usually one name.

    Both `seasons` and `competitor_seasons` read this, so the two cannot
    disagree about who won, which they used to: one picked a single name
    alphabetically and the other could mark several people champion.
    """
    board = snapshot["weighted"]
    if not board:
        return []
    best = max(board.values())
    return sorted(n for n, v in board.items() if v == best)


def eliminated_week(season: dict, name: str) -> Optional[int]:
    """The week a competitor's odds hit zero and never recovered.

    The start of the final unbroken run of zeros, which is what the chart draws.
    Taking the *first* zero instead called somebody eliminated in week 1 who was
    back at 5% in week 2.
    """
    ordered = sorted(season.get("snapshots") or [], key=lambda s: s["week"])
    if not ordered:
        return None
    start = None
    for snapshot in ordered:
        out = snapshot.get("eliminated")
        # Fall back to the rounded board for a snapshot written before
        # elimination was recorded structurally.
        zero = (name in out) if out is not None else (
            snapshot["weighted"].get(name, 1.0) == 0)
        if zero:
            if start is None:
                start = snapshot["week"]
        else:
            start = None
    return start


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
    "eagles_points", "champion", "co_champions", "champion_correct",
    "field_average",
]


def seasons_table(season: dict, current_week: Optional[int] = None) -> Table:
    year = season["year"]
    record = _record(season)
    snapshots = _snapshots(season)
    if current_week is None:
        current_week = max(snapshots) if snapshots else 0

    champion, champion_correct, field_average, co_champions = "", "", "", ""
    final = _final_snapshot(season)
    if final:
        correct = final.get("current_points") or {}
        winners = _champions(final)
        if winners:
            champion = winners[0]
            co_champions = ", ".join(winners[1:])
        if correct:
            # The champion is whoever the final board settled on, not simply the
            # top pick count, because the tiebreakers decide it.
            champion_correct = correct.get(champion, "")
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
        "co_champions": co_champions,
        "champion_correct": champion_correct,
        "field_average": field_average,
    }])


COMPETITOR_COLUMNS = [
    "slug", "name", "color", "first_season", "seasons_played", "titles",
    "title_years", "career_points", "all_time_rank",
]


def competitors_table(season: dict) -> Table:
    # colors_for completes a partial map: a competitor recorded earlier keeps
    # their colour, a newcomer gets the next unused hue. Reading the map
    # directly handed a newcomer an empty string, because a map that exists is
    # not the same as a map that is complete.
    colors = chart.colors_for(season["roster"], season.get("colors"))
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
            # Seasons on record, and nothing about the season doing the pushing.
            # This used to add one when the current season was not yet in
            # history, which made the answer depend on who was writing: a 2025
            # push said 10 and a 2026 push said 11, and since both seasons write
            # this table they overwrote each other on every run, forever.
            "seasons_played": len(seasons),
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
    final = _final_snapshot(season)
    winners = set(_champions(final)) if final else set()
    rows = []
    for name in _submitted(season):
        sheet = season["picks"][name]
        wins = sheet.count(engine.WIN)
        division_wins = sum(1 for i in division if sheet[i] == engine.WIN)
        eliminated = _blank(eliminated_week(season, name))
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
            "is_champion": name in winners,
        })
    return Table("competitor_seasons", COMPETITOR_SEASON_COLUMNS, rows)


# The Eagles' own name and abbreviation, so a row reads as a matchup rather
# than as "us and them". PHI is ESPN's, and every other abbreviation in these
# tables comes from ESPN, so it is the one that keeps the set consistent.
EAGLES = "Eagles"
EAGLES_ABBR = "PHI"

# A bye row still needs something in the abbreviation slots, because a matchup
# laid out from those two fields would otherwise render as a pair of blanks.
BYE_ABBR = "BYE"

GAME_COLUMNS = [
    "slug", "season", "week_ref", "nfl_week", "game_index", "event_id", "label",
    "is_bye", "home_team", "home_abbr", "away_team", "away_abbr", "venue",
    "neutral_site", "is_division", "kickoff", "result", "eagles_points",
    "opponent_points", "espn_weight",
]


def games_table(season: dict) -> Table:
    """Current state, deliberately. A result becomes known during the season.

    Nothing that needs a frozen view of the past should read this table; that is
    what `weeks` and `standings` are for.

    Every NFL week gets a row, including the bye. A bye is a week with no
    matchup rather than a week that does not exist, and leaving it out meant a
    schedule laid out from this table silently skipped a week.
    """
    year = season["year"]
    by_week = {g["nfl_week"]: g for g in season["games"]}
    byes = set(_bye_weeks(season))
    rows = []

    for week in sorted(set(by_week) | byes):
        game = by_week.get(week)
        base = {
            "slug": game_slug(year, week),
            "season": str(year),
            "week_ref": game_slug(year, week),
            "nfl_week": week,
        }
        if game is None:
            rows.append(dict(base, **{
                "game_index": "", "event_id": "", "label": "Bye",
                "is_bye": True, "home_team": "", "home_abbr": BYE_ABBR,
                "away_team": "", "away_abbr": BYE_ABBR, "venue": "",
                "neutral_site": False, "is_division": False, "kickoff": "",
                "result": "", "eagles_points": "", "opponent_points": "",
                "espn_weight": "",
            }))
            continue

        facts = game_facts(season, game)
        home = facts["home_away"] == "home"
        rows.append(dict(base, **{
            "game_index": game["index"],
            "event_id": facts["event_id"],
            "label": game["label"],
            "is_bye": False,
            # Stated as a matchup. Which side the Eagles are on comes from the
            # recorded `home` flag, not from the "vs."/"@" in the label, which
            # is wrong for a neutral-site game.
            "home_team": EAGLES if home else facts["opponent"],
            "home_abbr": EAGLES_ABBR if home else facts["opponent_abbr"],
            "away_team": facts["opponent"] if home else EAGLES,
            "away_abbr": facts["opponent_abbr"] if home else EAGLES_ABBR,
            "venue": facts["venue"],
            "neutral_site": facts["neutral_site"],
            "is_division": bool(game["division"]),
            "kickoff": _blank(game.get("date")),
            "result": "" if game["result"] == engine.UNPLAYED else game["result"],
            "eagles_points": _blank(game.get("points_for")),
            "opponent_points": _blank(game.get("points_against")),
            "espn_weight": _blank(game.get("weight")),
        }))
    return Table("games", GAME_COLUMNS, rows)


WEEK_COLUMNS = [
    "slug", "season", "week", "label", "is_bye", "game", "game_label",
    "opponent", "home_away", "result", "wins", "losses", "leader", "leader_pct",
    "remaining_outcomes", "still_alive", "decided_outright",
    # Appended September 2026, never inserted (see the module docstring). The
    # Decision Tree in full, its week-over-week movement, and the result the
    # standings carousel is a counterfactual of.
    "decided_tb1", "decided_tb2", "decided_tb3", "decided_split",
    "decided_outright_change", "decided_tb1_change", "decided_tb2_change",
    "decided_tb3_change", "counterfactual_result",
]

DECIDING_KEYS = ("outright", "tb1", "tb2", "tb3", "split")


def _game_facts_fallback(season: dict, game: dict) -> dict:
    """For a snapshot written before snapshots froze their own matchup."""
    facts = game_facts(season, game)
    return {
        "index": game["index"],
        "event_id": facts["event_id"],
        "label": game["label"],
        "opponent": facts["opponent"],
        "opponent_abbr": facts["opponent_abbr"],
        "home": game.get("home", facts["home_away"] == "home"),
        "neutral_site": facts["neutral_site"],
        "venue": facts["venue"],
        "result": game["result"],
    }


def weeks_table(season: dict) -> Table:
    """One frozen row per week, built from that week's snapshot.

    This is what a newsletter page reads for "the season as it stood then". The
    snapshot carries its own copy of the results, so a week's record cannot be
    contaminated by a game played afterwards.
    """
    year = season["year"]
    byes = set(_bye_weeks(season))
    by_week = {g["nfl_week"]: g for g in season["games"]}
    rows, previous_deciding, previous_week = [], None, None
    for snapshot in sorted(season.get("snapshots", []), key=lambda s: s["week"]):
        week = snapshot["week"]
        results = snapshot.get("results") or []
        deciding = snapshot.get("deciding") or {}
        # Movement only against the week immediately before, as standings.change
        # does: a gap reported as one week's move is worse than a blank.
        consecutive = previous_week is not None and week - previous_week == 1

        def decided(key):
            return round(float(deciding.get(key, 0) or 0), 1)

        def decided_change(key):
            if not consecutive or previous_deciding is None:
                return ""
            return round(decided(key) - round(float(previous_deciding.get(key, 0) or 0), 1), 1)

        # The result the carousel is a counterfactual of. Blank for week 0, a
        # bye, a tie and an unplayed game: those have no counterfactual and the
        # snapshot recorded none.
        hypothetical = (snapshot.get("counterfactual") or {}).get("hypothetical") or ""
        played = [r for r in results if r != engine.UNPLAYED]
        board = snapshot["weighted"]
        leader = max(board, key=lambda n: (board[n], n)) if board else ""

        # The matchup as recorded that week. Reading today's schedule instead
        # would mean a corrected opponent name, venue or result silently
        # rewriting a week that was published months ago.
        frozen_game = snapshot.get("game")
        if frozen_game is None and week in by_week:
            frozen_game = _game_facts_fallback(season, by_week[week])

        result = ""
        if frozen_game:
            index = frozen_game.get("index")
            if index is not None and index < len(results):
                current = results[index]
                result = "" if current == engine.UNPLAYED else current

        home = frozen_game.get("home") if frozen_game else None
        rows.append({
            "slug": "{}-w{:02d}".format(year, week),
            "season": str(year),
            "week": week,
            "label": "Preseason" if week == 0 else "Week {}".format(week),
            "is_bye": week in byes,
            "game": game_slug(year, week) if frozen_game else "",
            "game_label": (frozen_game["label"] if frozen_game
                           else ("Bye" if week in byes else "")),
            "opponent": ((frozen_game.get("opponent_name")
                          or frozen_game.get("opponent") or "")
                         if frozen_game else ""),
            "home_away": ("" if home is None else ("home" if home else "away")),
            "result": result,
            # Two numbers, not the string "5-2". Sheets parses that as the 5th
            # of February and hands back a Date, so the value written and the
            # value stored were different things. A page composes the record
            # from these; a spreadsheet cannot mangle an integer.
            "wins": played.count(engine.WIN),
            "losses": played.count(engine.LOSS),
            "leader": leader,
            "leader_pct": board.get(leader, "") if leader else "",
            "remaining_outcomes": snapshot.get("remaining_outcomes", ""),
            # From the structural field, not the rounded board: a long shot at
            # 0.04% is stored as 0.0 and was published here as finished. Same
            # fallback as eliminated_week and standings.is_eliminated.
            "still_alive": (len(board) - len(snapshot["eliminated"])
                            if snapshot.get("eliminated") is not None
                            else sum(1 for v in board.values() if v > 0)),
            "decided_outright": decided("outright"),
            "decided_tb1": decided("tb1"),
            "decided_tb2": decided("tb2"),
            "decided_tb3": decided("tb3"),
            "decided_split": decided("split"),
            "decided_outright_change": decided_change("outright"),
            "decided_tb1_change": decided_change("tb1"),
            "decided_tb2_change": decided_change("tb2"),
            "decided_tb3_change": decided_change("tb3"),
            "counterfactual_result": hypothetical,
        })
        previous_deciding, previous_week = deciding, week
    return Table("weeks", WEEK_COLUMNS, rows)


def _pick_is_correct(game: Optional[dict], sheet: Sequence[str]):
    """True, False, or blank while the game is unplayed or there is no game.

    Blank rather than False for the unknown cases, because False is a claim that
    the pick was wrong. A bye and a Sunday afternoon before kickoff are both
    "no answer yet", and rendering either as a red cross is a lie the table
    would be telling on its own.
    """
    if game is None:
        return ""
    result = game["result"]
    if result == engine.UNPLAYED:
        return ""
    return sheet[game["index"]] == result


# New columns are appended, never inserted. Framer maps a sheet column to a CMS
# field, and inserting one in the middle shifts every column after it. Even if
# that mapping is by header name and survives, appending costs nothing and
# removes the question.
PICK_COLUMNS = [
    "slug", "season", "week_ref", "nfl_week", "game", "competitor", "name",
    "pick", "is_bye", "correct",
]


def picks_table(season: dict) -> Table:
    """Written once a season and never again.

    One row per competitor per NFL week, including the bye, where `is_bye` is
    true and there is no pick. Skipping the bye left a hole in a grid laid out
    from this table, exactly as it did in `games`: nobody picked that week
    because there was no game, which is a fact about the week rather than a
    reason to omit it.

    `correct` is the one thing here that is not written once. It is blank until
    the game is settled and then holds True or False forever, which is the same
    shape as `games.result`, because it is that same fact seen from the pick's
    side. The table stays frozen everywhere else: the row never contradicts
    itself, since a cell only ever moves from "unknown" to the answer and never
    from one answer to another. The transport enforces exactly that much and no
    more -- `FILLABLE_COLUMNS` in `Code.gs` names this one column, and a
    `correct` that already holds an answer is refused like any other drift.

    Two things follow for anything reading it. A blank is "not yet", not "no",
    so a two-state renderer needs `is_bye` and the game's `result` to tell them
    apart. And the week a cell fills in is the week the game was played, not the
    week the row was written.

    Scored exactly as `engine.correct_picks_so_far` scores it, so the column and
    the board can never disagree: a pick is correct when the game is settled and
    the pick equals the result. A tie is settled and matches nobody, because no
    pick is ever "T", so a tie makes every pick that week False rather than
    blank. That is how the family scored the 2020 Bengals game.
    """
    year = season["year"]
    by_week = {g["nfl_week"]: g for g in season["games"]}
    byes = set(_bye_weeks(season))
    rows = []
    for name in _submitted(season):
        sheet = season["picks"][name]
        for week in sorted(set(by_week) | byes):
            key = game_slug(year, week)
            game = by_week.get(week)
            rows.append({
                "slug": "{}-{}".format(key, _slugify(name)),
                "season": str(year),
                "week_ref": key,
                "nfl_week": week,
                "game": key,
                "competitor": _slugify(name),
                "name": name,
                "is_bye": game is None,
                "pick": sheet[game["index"]] if game else "",
                "correct": _pick_is_correct(game, sheet),
            })
    return Table("picks", PICK_COLUMNS, rows)


STANDING_COLUMNS = [
    "slug", "season", "week", "week_ref", "competitor", "name",
    "weighted", "straight", "correct", "rank", "change", "is_eliminated",
    "is_bye",
    # Appended September 2026: the board had this week's result gone the other
    # way, for the standings carousel. All three blank when the snapshot has no
    # counterfactual (week 0, a bye, a tie, an unplayed game).
    "counterfactual_weighted", "counterfactual_rank", "counterfactual_change",
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

    rows, previous, previous_week = [], {}, None
    for snapshot in ordered:
        week = snapshot["week"]
        # Only compare against the week immediately before. If a week was never
        # snapshotted, the difference against the one before that is a two-week
        # move reported as one, which is worse than reporting nothing.
        consecutive = previous_week is not None and week - previous_week == 1
        board = snapshot["weighted"]
        out = snapshot.get("eliminated")
        ranks = _ranked(board)
        # From the snapshot only, like everything else here: a counterfactual
        # recomputed today would move with the weights and unfreeze the row.
        cf_board = (snapshot.get("counterfactual") or {}).get("board") or {}
        cf_ranks = _ranked(cf_board) if cf_board else {}
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
                "change": ("" if before is None or not consecutive
                           else round(board[name] - before, 1)),
                # The stored board is rounded to one decimal, so reading zero
                # off it published anyone under 0.05% as mathematically out --
                # and contradicted competitors.eliminated_week, which reads the
                # structural field. Same fallback as eliminated_week, so the two
                # tables cannot disagree about the same person in the same week.
                "is_eliminated": ((name in out) if out is not None
                                  else board[name] == 0),
                "is_bye": week in byes,
                "counterfactual_weighted": cf_board.get(name, ""),
                "counterfactual_rank": cf_ranks.get(name, ""),
                # Counterfactual minus actual: positive means the other result
                # would have been better for them.
                "counterfactual_change": (round(cf_board[name] - board[name], 1)
                                          if name in cf_board else ""),
            })
        previous, previous_week = dict(board), week
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
