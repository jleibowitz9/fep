#!/usr/bin/env python3
"""
The FEP weekly run, headless.

    python3 cli.py init            build the season file from the ESPN schedule
    python3 cli.py refresh         pull latest results, scores and weights
    python3 cli.py board           run the model and print the board
    python3 cli.py week [N]        the full weekly run (see below)
    python3 cli.py leverage        rank every remaining game by how much it matters
    python3 cli.py statpack [N]    print the stat pack for a week
    python3 cli.py push [--live]   push weekly percentages to the Google Sheet
    python3 cli.py picks <file>    load picks from a CSV

`week` is the one that matters. It refreshes from ESPN, runs the model, saves a
snapshot, writes the stat pack, renders the chart, and publishes the chart data.
Nothing is typed by hand.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fep import analytics, chart, engine, espn, publish, season as season_mod, sheets, statpack

YEAR = int(os.environ.get("FEP_YEAR", "2026"))
ROOT = os.path.dirname(os.path.abspath(__file__))


def _load():
    try:
        return season_mod.load(YEAR)
    except FileNotFoundError:
        sys.exit("No season file for {}. Run: python3 cli.py init".format(YEAR))


def _require_picks(season):
    if not season_mod.has_picks(season):
        sys.exit(
            "Picks are not loaded yet.\n"
            "  Add them to data/season_{}.json under \"picks\" and \"points_guess\",\n"
            "  or run: python3 cli.py picks <file.csv>".format(YEAR)
        )


def cmd_init():
    path = season_mod.path_for(YEAR)
    if os.path.exists(path):
        sys.exit("{} already exists. Use `refresh` instead.".format(path))
    season = season_mod.create(YEAR)
    season_mod.save(season)
    print("Created {}".format(path))
    print("  {} games, bye in week {}".format(len(season["games"]), season["bye_week"]))
    print("  division games at indices {}".format(season["division_indices"]))
    for game in season["games"]:
        weight = game["weight"]
        print("   {:>2}  wk{:<3} {:<24} {}".format(
            game["index"], game["nfl_week"], game["label"],
            "{:.1f}%".format(weight * 100) if weight is not None else "no line yet"))
    print("\nNext: add the 12 competitors' picks and points guesses.")


def cmd_refresh():
    season = _load()
    season_mod.refresh(season)
    season_mod.save(season)
    changes = season.get("last_refresh_changes") or []
    print("Refreshed from ESPN. {} change(s).".format(len(changes)))
    for change in changes:
        print("   {}".format(change))
    overrides = [g["index"] for g in season["games"]
                 if "manual" in (g.get("result_source"), g.get("weight_source"),
                                 g.get("points_source"))]
    if overrides:
        print("   (manual overrides preserved on game(s) {})".format(overrides))


def cmd_board():
    season = _load()
    _require_picks(season)
    board = season_mod.run(season)
    print("\n{} FEP after {} games ({:,} remaining outcomes)\n".format(
        YEAR, season_mod.games_played(season), board.remaining_outcomes))
    for name in board.ranked():
        bar = "#" * int(round(board.weighted[name] / 2))
        print("  {:<8} {:>5.1f}%  {:>2} correct  {}".format(
            name, board.weighted[name], board.current_points[name], bar))


def cmd_leverage():
    season = _load()
    _require_picks(season)
    rows = analytics.rank_leverage(season)
    if not rows:
        return print("No games left.")
    print("\nRemaining games by Leverage Index\n")
    for row in rows:
        print("  {:>5.1f}%  {}".format(row["leverage"], row["label"]))


def cmd_week(argv):
    season = _load()
    _require_picks(season)

    season_mod.refresh(season)
    for change in season.get("last_refresh_changes") or []:
        print("  espn: {}".format(change))

    week = int(argv[0]) if argv else season_mod.current_nfl_week(season)
    # Pin the board to the end of that week. ESPN may already have a result from
    # a later week (a Thursday game, or a newsletter written late), and that must
    # not leak into this week's snapshot.
    board = season_mod.run(season, through_week=week)
    season_mod.snapshot(season, week, board)
    season_mod.save(season)

    pack = analytics.full_pack(season, board, week, through_week=week)

    pack_path = os.path.join(ROOT, "newsletters", "week-{:02d}".format(week), "statpack.md")
    statpack.write(season, board, week, pack_path, pack)

    chart_path = os.path.join(ROOT, "newsletters", "week-{:02d}".format(week),
                              "chart.html")
    with open(chart_path, "w") as fh:
        fh.write(chart.render_from_season(season, upto_week=week))

    published = publish.publish_from_season(season, week=week)

    print("\n{} FEP | Week {}{}".format(
        YEAR, week, "  (bye week)" if pack["is_bye"] else ""))
    print("{:,} remaining outcomes, {} still alive\n".format(
        board.remaining_outcomes, pack["concentration"]["alive"]))
    for name in board.ranked():
        delta = pack["heat_check"]["deltas"].get(name)
        arrow = "" if delta in (None, 0) else ("  {:+.1f}".format(delta))
        print("  {:<8} {:>5.1f}%{}".format(name, board.weighted[name], arrow))

    print("\n  stat pack   {}".format(os.path.relpath(pack_path, ROOT)))
    print("  chart       {}".format(os.path.relpath(chart_path, ROOT)))
    print("  chart data  {}".format(os.path.relpath(published[0], ROOT)))
    print("\nNext: python3 cli.py push        (dry run, shows what would be written)")
    print("      python3 cli.py push --live  (writes B2:M20)")


def cmd_statpack(argv):
    season = _load()
    _require_picks(season)
    week = int(argv[0]) if argv else season_mod.current_nfl_week(season)
    board = season_mod.run(season, through_week=week)
    print(statpack.render(season, board, week))


def cmd_push(argv):
    season = _load()
    live = "--live" in argv
    tab = None
    for arg in argv:
        if arg.startswith("--tab="):
            tab = arg.split("=", 1)[1]

    if not live:
        result = sheets.push(season, tab=tab, dry_run=True)
        print("DRY RUN. Would write {} rows x {} columns to {}\n".format(
            result["rows"], result["columns"], result["range"]))
        first_week = season["sheet"].get("first_week", 0)
        for offset, row in enumerate(result["values"]):
            if any(cell != "" for cell in row):
                print("  wk {:>2}  {}".format(first_week + offset,
                                              "  ".join("{:>5}".format(c) for c in row)))
        print("\nColumn A and everything from column N rightward are never touched.")
        print("Re-run with --live to write. Use --tab=Scratch to target a copy first.")
        return

    result = sheets.push(season, tab=tab)
    print("Wrote {} cells to {}".format(result["updated_cells"], result["updated_range"]))


def cmd_picks(argv):
    """Load picks from a CSV: Competitor,PointsGuess,G1..G17 (W/L)."""
    import csv
    if not argv:
        sys.exit("usage: python3 cli.py picks <file.csv>")
    season = _load()
    games = len(season["games"])

    picks, guesses = {}, {}
    with open(argv[0]) as fh:
        for row in csv.reader(fh):
            if not row or row[0].strip().lower() in ("competitor", "name", ""):
                continue
            name = row[0].strip()
            guesses[name] = int(float(row[1]))
            sheet = [cell.strip().upper()[:1] for cell in row[2:2 + games]]
            picks[name] = sheet

    engine.validate(picks, season_mod.results(season), season_mod.weights(season),
                    season["division_indices"], guesses)
    season["picks"] = picks
    season["points_guess"] = guesses
    season["roster"] = sorted(picks)
    season_mod.save(season)
    print("Loaded {} pick sheets of {} games each.".format(len(picks), games))
    for name in season["roster"]:
        wins = picks[name].count("W")
        div = sum(1 for i in season["division_indices"] if picks[name][i] == "W")
        print("  {:<8} {}-{}   division {}-{}   {} points".format(
            name, wins, games - wins, div, len(season["division_indices"]) - div,
            guesses[name]))


COMMANDS = {
    "init": lambda a: cmd_init(),
    "refresh": lambda a: cmd_refresh(),
    "board": lambda a: cmd_board(),
    "leverage": lambda a: cmd_leverage(),
    "week": cmd_week,
    "statpack": cmd_statpack,
    "push": cmd_push,
    "picks": cmd_picks,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    command = sys.argv[1]
    if command not in COMMANDS:
        sys.exit("Unknown command {!r}. Try --help.".format(command))
    try:
        COMMANDS[command](sys.argv[2:])
    except (engine.SeasonError, sheets.SheetError, espn.ESPNError) as exc:
        sys.exit("Error: {}".format(exc))


if __name__ == "__main__":
    main()
