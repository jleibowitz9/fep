"""
ESPN data pull for the FEP.

This module replaces the most tedious part of Jacob's week: opening the Eagles
team page, clicking into every remaining game, and reading the matchup-predictor
percentage off each one.

Two public ESPN endpoints do all the work:

  schedule   site.api.espn.com/apis/site/v2/sports/football/nfl/teams/phi/schedule
             -> the 17-game regular season, opponents, dates, event ids,
                final scores and winner flags

  predictor  sports.core.api.espn.com/v2/.../events/<id>/competitions/<id>/predictor
             -> "gameProjection", which IS the matchup-predictor win percentage
                shown on the site. This is the number that becomes weight[i].

Everything is cached to data/espn_cache/ so a refresh is one round trip and
re-runs work offline.

Nothing here decides anything. It returns facts; the caller stores them in the
season file, where any value can be overridden by hand.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

TEAM = "phi"
TEAM_ABBR = "PHI"

SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/"
    "{team}/schedule?season={year}&seasontype=2"
)
PREDICTOR_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{event_id}/competitions/{event_id}/predictor"
)

# NFC East. Used to derive division_weeks straight off the schedule rather than
# asking anyone to hand-maintain a list of indices.
DIVISION_OPPONENTS = {"DAL", "NYG", "WSH"}

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "espn_cache")

# Deliberately no custom User-Agent.
#
# ESPN's edge fronting these endpoints 403s a custom UA string AND a
# browser-like one ("Mozilla/5.0 ... Chrome/126"), but happily serves the stock
# "Python-urllib/3.x" and "curl/8.x". Verified by trying all four. So the right
# move is to send nothing and let urllib use its default. If you are here
# because requests started 403ing, check whether something added a UA header.


class ESPNError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, key + ".json")


def _read_cache(key: str, max_age_s: Optional[float]) -> Optional[dict]:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    if max_age_s is not None and (time.time() - os.path.getmtime(path)) > max_age_s:
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_cache(key: str, payload: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _cache_path(key) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, _cache_path(key))


def _get(url: str, cache_key: str, max_age_s: Optional[float], timeout: float = 25.0) -> dict:
    """Fetch JSON, falling back to cache on any network failure.

    max_age_s=None means "use the cache no matter how old". That is what makes
    the whole tool work on a plane.
    """
    cached = _read_cache(cache_key, max_age_s)
    if cached is not None:
        return cached

    req = urllib.request.Request(url)  # see the USER_AGENT note above
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        stale = _read_cache(cache_key, None)
        if stale is not None:
            return stale
        raise ESPNError("could not reach ESPN and no cached copy exists: {}".format(exc))

    _write_cache(cache_key, payload)
    return payload


# ---------------------------------------------------------------------------
# schedule, results, points
# ---------------------------------------------------------------------------

def fetch_schedule(year: int, refresh: bool = False) -> List[dict]:
    """Return the regular season as a list of game dicts, index-aligned to picks.

    Each entry:
        index        0-based position in the 17-game pick array
        nfl_week     NFL week number (diverges from index after the bye)
        event_id     ESPN event id, needed for the predictor endpoint
        opponent     opponent abbreviation, e.g. "WSH"
        label        display label, e.g. "vs. Commanders"
        home         True if the Eagles are the home team
        date         ISO date string
        division     True if the opponent is NFC East
        result       'W' / 'L' / 'A' (A = not yet played)
        points_for   Eagles points, or None if unplayed
        points_against
        status       ESPN status name, e.g. STATUS_FINAL
    """
    payload = _get(
        SCHEDULE_URL.format(team=TEAM, year=year),
        cache_key="schedule_{}".format(year),
        max_age_s=0 if refresh else 6 * 3600,
    )

    events = payload.get("events") or []
    games: List[dict] = []

    for event in events:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]

        phi = opp = None
        for competitor in comp.get("competitors") or []:
            if (competitor.get("team") or {}).get("abbreviation") == TEAM_ABBR:
                phi = competitor
            else:
                opp = competitor
        if phi is None or opp is None:
            continue

        status = ((comp.get("status") or {}).get("type") or {})
        completed = bool(status.get("completed"))

        result = "A"
        if completed:
            # ESPN sets `winner` on both sides once a game is final.
            if phi.get("winner") is True:
                result = "W"
            elif phi.get("winner") is False:
                result = "L"

        opp_team = opp.get("team") or {}
        opp_abbr = opp_team.get("abbreviation") or ""
        # "shortDisplayName" / "nickname" are the team nickname ("Commanders").
        # There is no "name" key on this payload, so falling through to the
        # abbreviation would silently give newsletter labels like "vs. WSH".
        nickname = opp_team.get("shortDisplayName") or opp_team.get("nickname") or opp_abbr

        home = phi.get("homeAway") == "home"
        venue = comp.get("venue") or {}
        neutral = bool(comp.get("neutralSite"))
        city = (venue.get("address") or {}).get("city")

        # A neutral-site game is neither home nor away. Calling the 2026 London
        # game "@ Jaguars" would be wrong in print, so label it by its city.
        if neutral:
            label = "vs. {}{}".format(nickname, " ({})".format(city) if city else " (neutral)")
        else:
            label = "{} {}".format("vs." if home else "@", nickname)

        games.append(
            {
                "index": len(games),
                "nfl_week": (event.get("week") or {}).get("number"),
                "event_id": str(event.get("id")),
                "opponent": opp_abbr,
                "label": label,
                "home": home,
                "neutral_site": neutral,
                "venue": venue.get("fullName"),
                "date": (event.get("date") or "")[:10],
                "division": opp_abbr in DIVISION_OPPONENTS,
                "result": result,
                "points_for": _score(phi) if completed else None,
                "points_against": _score(opp) if completed else None,
                "status": status.get("name"),
            }
        )

    if not games:
        raise ESPNError("ESPN returned no regular-season games for {}".format(year))
    return games


def _score(competitor: dict) -> Optional[int]:
    raw = competitor.get("score")
    if isinstance(raw, dict):
        raw = raw.get("displayValue", raw.get("value"))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def division_indices(games: List[dict]) -> List[int]:
    """The game indices that count toward tiebreaker 2."""
    return [g["index"] for g in games if g["division"]]


def week_to_game_index(games: List[dict]) -> Dict[int, Optional[int]]:
    """Map every NFL week (1..18) to a game index, with None for the bye.

    The board has a row per NFL week but the season has only 17 games, so these
    two numberings diverge after the bye. Deriving the map from the schedule
    keeps that from ever being hand-maintained (and hand-broken).
    """
    by_week = {g["nfl_week"]: g["index"] for g in games if g["nfl_week"]}
    if not by_week:
        return {}
    last = max(by_week)
    return {week: by_week.get(week) for week in range(1, last + 1)}


def bye_week(games: List[dict]) -> Optional[int]:
    for week, index in week_to_game_index(games).items():
        if index is None:
            return week
    return None


# ---------------------------------------------------------------------------
# the matchup predictor
# ---------------------------------------------------------------------------

def fetch_weight(event_id: str, refresh: bool = False) -> Optional[float]:
    """Eagles win probability for one game, as a 0..1 float.

    Reads `gameProjection` off whichever side is Philadelphia. That statistic is
    exactly what the site's matchup predictor displays.

    Returns None when ESPN has no prediction (which happens for games far out,
    and for games already final). The caller decides what to do about it.
    """
    try:
        payload = _get(
            PREDICTOR_URL.format(event_id=event_id),
            cache_key="predictor_{}".format(event_id),
            max_age_s=0 if refresh else 3 * 3600,
        )
    except ESPNError:
        return None

    for side in ("homeTeam", "awayTeam"):
        block = payload.get(side) or {}
        team_ref = (block.get("team") or {}).get("$ref", "")
        if not _ref_is_eagles(team_ref):
            continue
        for stat in block.get("statistics") or []:
            if stat.get("name") == "gameProjection":
                value = stat.get("value", stat.get("displayValue"))
                try:
                    return round(float(value) / 100.0, 4)
                except (TypeError, ValueError):
                    return None
    return None


# ESPN's NFL team id for Philadelphia. The predictor payload identifies teams by
# $ref URL rather than abbreviation, so we match on the id path segment.
EAGLES_TEAM_ID = "21"


def _ref_is_eagles(ref: str) -> bool:
    if not ref:
        return False
    path = ref.split("?")[0].rstrip("/")
    return path.rsplit("/", 1)[-1] == EAGLES_TEAM_ID


def fetch_weights(games: List[dict], refresh: bool = False) -> Dict[int, Optional[float]]:
    """Matchup-predictor weights for every game, keyed by game index."""
    return {g["index"]: fetch_weight(g["event_id"], refresh=refresh) for g in games}


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------

def fetch_season(year: int, refresh: bool = False) -> dict:
    """One call that returns everything the season file needs from ESPN."""
    games = fetch_schedule(year, refresh=refresh)
    weights = fetch_weights(games, refresh=refresh)
    for game in games:
        game["weight"] = weights.get(game["index"])
    return {
        "year": year,
        "games": games,
        "results": [g["result"] for g in games],
        "points_for": [g["points_for"] for g in games],
        "weights": [g["weight"] for g in games],
        "division_indices": division_indices(games),
        "week_to_game_index": week_to_game_index(games),
        "bye_week": bye_week(games),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
