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


def publish_week(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]],
    year: int,
    week: int,
    out_dir: Optional[str] = None,
) -> str:
    payload = chart.build_payload(
        weeks=weeks, board_by_week=board_by_week, roster=roster,
        games=games, year=year, upto_week=week,
    )
    directory = out_dir or os.path.join(CHART_DATA_DIR, str(year))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, week_filename(week))
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def publish_all(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]],
    year: int,
    out_dir: Optional[str] = None,
) -> List[str]:
    """Republish every week that has data. Cheap, and keeps corrections honest."""
    return [
        publish_week(weeks, board_by_week, roster, games, year, week, out_dir)
        for week in sorted(weeks)
    ]


def publish_from_season(season: dict, week: Optional[int] = None,
                        out_dir: Optional[str] = None) -> List[str]:
    """Publish straight from a season file's snapshots."""
    snapshots = {s["week"]: s["weighted"] for s in season.get("snapshots", [])}
    if not snapshots:
        raise ValueError("season has no snapshots yet")

    games = {g["nfl_week"]: {"label": g["label"], "result": g["result"]}
             for g in season["games"]}
    bye = season.get("bye_week")
    if bye:
        games[bye] = {"label": "Bye", "result": None}

    weeks = sorted(snapshots)
    args = (weeks, snapshots, season["roster"], games, season["year"])
    if week is None:
        return publish_all(*args, out_dir=out_dir)
    return [publish_week(*args, week=week, out_dir=out_dir)]
