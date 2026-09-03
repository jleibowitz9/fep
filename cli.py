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
    python3 cli.py token           generate a shared secret for the Apps Script
    python3 cli.py dashboard       build and open the weekly dashboard
    python3 cli.py picks <file>    load picks from a CSV

    python3 cli.py who <name>      career record and picking personality
    python3 cli.py h2h <a> <b>     head to head across every shared season
    python3 cli.py retro <year>    replay a past season through the model

`week` is the one that matters. It refreshes from ESPN, runs the model, saves a
snapshot, writes the stat pack, renders the chart, and publishes the chart data.
Nothing is typed by hand.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fep import (analytics, chart, engine, espn, history, publish,
                 season as season_mod, sheets, statpack)

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
        configured = ("Apps Script" if sheets.appsscript_available()
                      else ("service account" if sheets.credentials_available()
                            else "NOTHING CONFIGURED, paste the block below"))
        print("DRY RUN via {}. Would write {} rows x {} columns to {}\n".format(
            configured, result["rows"], result["columns"], result["range"]))
        first_week = season["sheet"].get("first_week", 0)
        for offset, row in enumerate(result["values"]):
            if any(cell != "" for cell in row):
                print("  wk {:>2}  {}".format(first_week + offset,
                                              "  ".join("{:>5}".format(c) for c in row)))
        print("\nColumn A and everything from column N rightward are never touched,")
        print("by this tool and by the Apps Script independently.")
        if not (sheets.appsscript_available() or sheets.credentials_available()):
            print("\nNothing is configured yet, so paste this block into cell B2:\n")
            print(sheets.to_tsv_block(season))
            print("\nOr run `python3 cli.py token` and see appsscript/README.md")
            print("to set up the one-click push.")
        else:
            print("Re-run with --live to write. Use --tab=Scratch to target a copy first.")
        return

    result = sheets.push(season, tab=tab)
    print("Wrote {} cells to {}".format(result["updated_cells"], result["updated_range"]))


def cmd_dashboard(argv):
    """Build the single-file dashboard for a week and open it."""
    import subprocess
    sys.path.insert(0, os.path.join(ROOT, "dashboard"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dashboard_build", os.path.join(ROOT, "dashboard", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    mock = next((a.split("=", 1)[1] for a in argv if a.startswith("--mock=")), None)
    week = next((int(a) for a in argv if a.isdigit()), None)
    data = (__import__("json").load(open(mock)) if mock
            else module.collect(YEAR, week))
    path = module.build(data)
    print("Built {} ({:.0f} KB)".format(
        os.path.relpath(path, ROOT), os.path.getsize(path) / 1024))
    if "--no-open" not in argv:
        subprocess.run(["open", path], check=False)


def cmd_token(argv):
    """Generate the shared secret that pairs the CLI with the Apps Script."""
    import json
    token = sheets.new_token()
    config_path = sheets.APPSSCRIPT_CONFIG
    print("\nShared secret (paste into Apps Script > Project Settings >")
    print("Script properties, as FEP_TOKEN):\n")
    print("   " + token)
    print("\nThen save this alongside your deployment URL at")
    print("   " + os.path.relpath(config_path, ROOT))
    print("\n" + json.dumps({"url": "PASTE_YOUR_/exec_URL_HERE", "token": token}, indent=2))
    print("\nThat file is gitignored. Anyone holding both the URL and the token")
    print("can write your weekly percentages, so treat it like a password.")


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


def cmd_who(argv):
    if not argv:
        sys.exit("usage: python3 cli.py who <name>")
    name = argv[0].capitalize()
    record = history.career(name)
    print("\n{}  (all-time #{}, {} career points)".format(
        name, record["all_time_place"], record["career_points"]))
    print("  seasons     {} ({} to {})".format(
        len(record["seasons"]), record["first_season"], record["seasons"][-1]))
    print("  titles      {} {}".format(
        record["championships"],
        record["title_years"] if record["title_years"] else ""))
    print("  best        {} place in {}".format(record["best_finish"], record["best_finish_year"]))
    print("  worst       {} place in {}".format(record["worst_finish"], record["worst_finish_year"]))
    print("  average     {} place, {} correct picks".format(
        record["average_place"], record["average_correct"]))
    print("  top 3 / bottom 3: {} / {}".format(record["top3"], record["bottom3"]))
    try:
        p = history.pick_personality(name)
        print("\n  picks {:+.2f} wins vs reality, {}% accurate".format(p["optimism"], p["accuracy"]))
        print("  goes against the field {}% of the time".format(p["contrarian_rate"]))
        print("  backs the Eagles in {}% of division games".format(p["division_faith"]))
    except history.HistoryError:
        pass
    print("\nReady-made lines:")
    for line in history.context_lines(name):
        print("  " + line)


def cmd_h2h(argv):
    if len(argv) < 2:
        sys.exit("usage: python3 cli.py h2h <a> <b>")
    a, b = argv[0].capitalize(), argv[1].capitalize()
    result = history.head_to_head(a, b)
    print("\n{}\n".format(result["summary"]))
    print("  {:<6} {:>18} {:>18}".format("year", a, b))
    for row in result["detail"]:
        star = lambda n: "*" if row["winner"] == n else " "
        print("  {:<6} {:>16} {}{:>16} {}".format(
            row["year"],
            "{} ({})".format(row[a]["place"], row[a]["correct"]), star(a),
            "{} ({})".format(row[b]["place"], row[b]["correct"]), star(b)))
    print("\n  shown as place (correct picks). * = finished ahead.")


def cmd_retro(argv):
    if not argv:
        sys.exit("usage: python3 cli.py retro <year>")
    year = int(argv[0])
    r = history.retro_season(year)
    print("\n{} replayed  (Eagles {}, {} competitors)".format(
        year, r["record"], len(r["competitors"])))
    print("  " + r["method"])
    for note in r["notes"]:
        print("  note: " + note)
    print("\n  final standings")
    for name, score in sorted(r["final_correct"].items(), key=lambda kv: -kv[1]):
        print("    {:<8} {}".format(name, score))
    print("\n  decided after game {} of {} ({} to spare)".format(
        r["decided_after_game"], r["games"], r["games_to_spare"]))
    if r["eliminations"]:
        print("\n  eliminations")
        for name, game in r["eliminations"].items():
            print("    {:<8} after game {}".format(name, game))
    if r["lead_changes"]:
        print("\n  lead changes")
        for change in r["lead_changes"]:
            print("    after game {:>2}: {} -> {}".format(
                change["after_game"], change["from"], change["to"]))


COMMANDS = {
    "init": lambda a: cmd_init(),
    "refresh": lambda a: cmd_refresh(),
    "board": lambda a: cmd_board(),
    "leverage": lambda a: cmd_leverage(),
    "week": cmd_week,
    "statpack": cmd_statpack,
    "push": cmd_push,
    "picks": cmd_picks,
    "token": cmd_token,
    "dashboard": cmd_dashboard,
    "who": cmd_who,
    "h2h": cmd_h2h,
    "retro": cmd_retro,
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
    except (engine.SeasonError, sheets.SheetError, espn.ESPNError,
            history.HistoryError) as exc:
        sys.exit("Error: {}".format(exc))


if __name__ == "__main__":
    main()
