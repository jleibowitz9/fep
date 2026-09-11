"""
Publish chart data for the Framer component.

Writes one immutable JSON file per week to chart-data/<year>/week-NN.json.

WHY ONE FILE PER WEEK
---------------------
The Framer component takes a single `week` number. It fetches
`${baseUrl}/week-07.json`, which contains weeks 0 through 7 and nothing after.
Two things fall out of that:

  Immutability. An old newsletter cannot start showing future weeks, because
  its file does not contain them. This is what replaces the old approach of a
  hidden "Weighted - W7" sheet tab plus a chart-component variant per week.

  Caching. Each URL's content never changes, so a CDN can cache it forever and
  there is no stale-data window after a weekly update. New week, new URL.

Corrections still work: republish that week's file and it propagates.

HOSTING
-------
Any static host with permissive CORS. Committing these to the public
eagles-simulator repo is enough, since both of these serve
`access-control-allow-origin: *` with no setup:

  https://raw.githubusercontent.com/<user>/<repo>/main/chart-data/2026
  https://cdn.jsdelivr.net/gh/<user>/<repo>@main/chart-data/2026
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence

from . import chart

ROOT = os.path.dirname(os.path.dirname(__file__))
CHART_DATA_DIR = os.path.join(ROOT, "chart-data")


def week_filename(week: int) -> str:
    return "week-{:02d}.json".format(week)


class PublishedWeekError(Exception):
    """A published week was asked to become something else."""


def publish_week(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]],
    year: int,
    week: int,
    out_dir: Optional[str] = None,
    colors: Optional[Dict[str, str]] = None,
    eliminated: Optional[Dict[int, Sequence[str]]] = None,
    correction: Optional[str] = None,
    deciding: Optional[Dict[int, Dict[str, float]]] = None,
    outcomes: Optional[Dict[int, int]] = None,
) -> str:
    """Write one week's chart file. A week already published does not move.

    The immutability this module's docstring promises was, until now, only a
    property of the payload: week 7's file cannot show week 8 because it does
    not contain week 8. But nothing stopped week 7's file being rewritten with
    a different week 7. A URL a newsletter has already sent out is a promise,
    and a CDN told to cache it forever will honour whichever version it saw
    first anyway -- so a silent rewrite is not even reliably a rewrite.

    An identical republish is therefore a no-op down to the file's mtime, and a
    changed one is refused unless it is declared a correction. Same contract as
    `season.snapshot`, for the same reason.
    """
    payload = chart.build_payload(
        weeks=weeks, board_by_week=board_by_week, roster=roster,
        games=games, year=year, upto_week=week, colors=colors,
        eliminated=eliminated, deciding=deciding, outcomes=outcomes,
    )
    directory = out_dir or os.path.join(CHART_DATA_DIR, str(year))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, week_filename(week))
    body = json.dumps(payload, separators=(",", ":"))

    if os.path.exists(path) and not correction:
        with open(path) as fh:
            existing = fh.read()
        if existing == body:
            return path       # byte for byte the same; leave the file alone
        raise PublishedWeekError(
            "chart-data/{}/{} is already published and this run would change "
            "it.\n  A published week is a URL that has already gone out. If "
            "this is a genuine\n  correction, say so: python3 cli.py week {} "
            "--correction \"why\"".format(year, week_filename(week), week))

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(body)
    os.replace(tmp, path)
    return path


def publish_all(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]],
    year: int,
    out_dir: Optional[str] = None,
    colors: Optional[Dict[str, str]] = None,
    eliminated: Optional[Dict[int, Sequence[str]]] = None,
    correction: Optional[str] = None,
    deciding: Optional[Dict[int, Dict[str, float]]] = None,
    outcomes: Optional[Dict[int, int]] = None,
) -> List[str]:
    """Republish every week that has data. Cheap, and keeps corrections honest."""
    return [
        publish_week(weeks, board_by_week, roster, games, year, week, out_dir,
                     colors, eliminated, correction, deciding, outcomes)
        for week in sorted(weeks)
    ]


def publish_from_season(season: dict, week: Optional[int] = None,
                        out_dir: Optional[str] = None,
                        correction: Optional[str] = None) -> List[str]:
    """Publish straight from a season file's snapshots."""
    snapshots = {s["week"]: s["weighted"] for s in season.get("snapshots", [])}
    if not snapshots:
        raise ValueError("season has no snapshots yet")

    games = {g["nfl_week"]: {"label": g["label"], "result": g["result"]}
             for g in season["games"]}
    for bye in (season.get("bye_weeks")
                or ([season["bye_week"]] if season.get("bye_week") else [])):
        games[bye] = {"label": "Bye", "result": None}

    weeks = sorted(snapshots)
    args = (weeks, snapshots, season["roster"], games, season["year"])
    # The season's recorded colours and its unrounded elimination, so a
    # published chart says the same thing as the CMS and the dashboard. Without
    # these the payload fell back to deriving both, and a competitor not in the
    # canonical twelve came out with no colour at all.
    extra = {
        "colors": chart.colors_for(season["roster"], season.get("colors")),
        "eliminated": {s["week"]: s["eliminated"]
                       for s in season.get("snapshots", [])
                       if s.get("eliminated") is not None} or None,
        # The Decision Tree, per week, from the same frozen record. This is
        # what lets the Framer component's Auto source work with no CMS column.
        "deciding": {s["week"]: s["deciding"]
                     for s in season.get("snapshots", [])
                     if s.get("deciding")} or None,
        "outcomes": {s["week"]: s["remaining_outcomes"]
                     for s in season.get("snapshots", [])
                     if s.get("remaining_outcomes") is not None} or None,
    }
    if week is None:
        return publish_all(*args, out_dir=out_dir, correction=correction, **extra)
    return [publish_week(*args, week=week, out_dir=out_dir,
                         correction=correction, **extra)]
