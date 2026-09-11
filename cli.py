#!/usr/bin/env python3
"""
The FEP weekly run, headless.

    python3 cli.py init            build the season file from the ESPN schedule
    python3 cli.py refresh         pull latest results, scores and weights
    python3 cli.py board           run the model and print the board
    python3 cli.py week [N]        the full weekly run (see below)
    python3 cli.py leverage        rank every remaining game by how much it matters
    python3 cli.py statpack [N]    print the stat pack for a week
    python3 cli.py cms [--live]    build (and push) the seven CMS tables
    python3 cli.py token           generate a shared secret for the Apps Script
    python3 cli.py dashboard       build and open the weekly dashboard
    python3 cli.py picks <file>    load picks from a CSV
    python3 cli.py override <game> <field> <value|--clear>
                                   pin a result, weight or score by hand

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

from fep import (analytics, chart, engine, espn, history, manifest, publish,
                 season as season_mod, sheets, statpack)

YEAR = int(os.environ.get("FEP_YEAR", "2026"))
ROOT = os.path.dirname(os.path.abspath(__file__))


def _load():
    try:
        return season_mod.load(YEAR)
    except FileNotFoundError:
        sys.exit("No season file for {}. Run: python3 cli.py init".format(YEAR))


def _require_picks(season):
    if season_mod.has_picks(season):
        return
    missing = [n for n in season["roster"] if not season["picks"].get(n)]
    if missing and len(missing) < len(season["roster"]):
        sys.exit(
            "Waiting on {} of {} pick sheets: {}.\n"
            "  Load them with: python3 cli.py picks <file.csv>".format(
                len(missing), len(season["roster"]), ", ".join(missing)))
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

    # A rewrite of a week that has already gone out has to be asked for by
    # name, and says why. `--correction "ESPN corrected the Week 4 score"`.
    correction = None
    positional = []
    skip = -1
    for index, arg in enumerate(argv):
        if index == skip:
            continue          # the reason, already consumed by the flag
        if arg == "--correction":
            correction = argv[index + 1] if index + 1 < len(argv) else ""
            skip = index + 1
        elif arg.startswith("--correction="):
            correction = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            positional.append(arg)
    if correction is not None and not str(correction).strip():
        raise SystemExit("--correction needs a reason. It goes into the record.")

    # The calendar decides which week this is, not the scoreboard. A bye week
    # never produces a result, so defaulting to the last week that did would
    # re-run the week before the bye and leave the bye itself unrecorded.
    week = int(positional[0]) if positional else season_mod.week_to_run(season)
    # A snapshot freezes, so a week must not be recorded before it happens.
    #
    # week_to_run reads the calendar and ISO dates compare as strings, so it
    # steps onto a week at midnight rather than at kickoff. Running on a Sunday
    # morning therefore pinned a pre-game board as the week, and the real run
    # that evening was refused as drift and needed --correction "why" -- an
    # audit entry for an early click rather than for a genuine correction.
    #
    # Only the calendar's own answer is guarded. Naming a week is a deliberate
    # act and still records whatever is there, which is what backfills need.
    index = season_mod.game_index_for_week(season, week)
    if not positional and index is not None \
            and season["games"][index]["result"] == engine.UNPLAYED:
        raise SystemExit(
            "Week {} has not been played yet ({} is still unplayed).\n"
            "  A snapshot freezes, so recording it now would pin a pre-game\n"
            "  board and the real one would then need --correction. Run this\n"
            "  after the game, or say `cli.py week {}` to record it anyway.".format(
                week, season["games"][index]["label"], week))
    # Pin the board to the end of that week. ESPN may already have a result from
    # a later week (a Thursday game, or a newsletter written late), and that must
    # not leak into this week's snapshot.
    board = season_mod.run(season, through_week=week)
    entry, status = season_mod.snapshot(season, week, board,
                                        correction=correction)
    season_path = season_mod.save(season)

    pack = analytics.full_pack(season, board, week, through_week=week)

    pack_path = os.path.join(ROOT, "newsletters", "week-{:02d}".format(week), "statpack.md")
    statpack.write(season, board, week, pack_path, pack)

    chart_path = os.path.join(ROOT, "newsletters", "week-{:02d}".format(week),
                              "chart.html")
    with open(chart_path, "w") as fh:
        fh.write(chart.render_from_season(season, upto_week=week))

    published = publish.publish_from_season(season, week=week,
                                            correction=correction)

    # Write down exactly what this run produced, so whatever archives it stages
    # these files rather than three whole directories that may also be holding
    # somebody else's work in progress.
    manifest.write(week, [season_path, pack_path, chart_path] + list(published))

    print("\n{} FEP | Week {}{}{}".format(
        YEAR, week, "  (bye week)" if pack["is_bye"] else "",
        {"unchanged": "  (already recorded, unchanged)",
         "corrected": "  (CORRECTED)"}.get(status, "")))
    # "Alive" is a claim about the rules. concentration.alive is deliberately
    # the other notion (measurable odds) and stays that way for the field
    # readout; the sentence that says "alive" reads the rules.
    print("{:,} remaining outcomes, {} still alive\n".format(
        board.remaining_outcomes, len(pack["elimination"]["alive"])))
    for name in board.ranked():
        delta = pack["heat_check"]["deltas"].get(name)
        arrow = "" if delta in (None, 0) else ("  {:+.1f}".format(delta))
        print("  {:<8} {:>5.1f}%{}".format(name, board.weighted[name], arrow))

    print("\n  stat pack   {}".format(os.path.relpath(pack_path, ROOT)))
    print("  chart       {}".format(os.path.relpath(chart_path, ROOT)))
    print("  chart data  {}".format(os.path.relpath(published[0], ROOT)))
    print("\nNext: python3 cli.py cms         (dry run, shows what would be written)")
    print("      python3 cli.py cms --live   (writes the seven CMS tables)")


def cmd_statpack(argv):
    season = _load()
    _require_picks(season)
    week = int(argv[0]) if argv else season_mod.current_nfl_week(season)
    board = season_mod.run(season, through_week=week)
    print(statpack.render(season, board, week))


def cmd_cms(argv):
    """Build the seven CMS tables, and optionally write them to the Sheet."""
    season = _load()
    live = "--live" in argv
    out_dir = next((a.split("=", 1)[1] for a in argv if a.startswith("--csv=")), None)
    if out_dir is None and "--csv" in argv:
        out_dir = os.path.join(ROOT, "exports", "cms")
    only = next((a.split("=", 1)[1].split(",") for a in argv
                 if a.startswith("--only=")), None)

    if out_dir:
        for path in sheets.tables_to_csv(season, out_dir):
            print("  {:>7,} bytes  {}".format(os.path.getsize(path), path))
        return

    if not live:
        from fep import cms
        tables = cms.tables(season)
        print("\n{} CMS tables\n".format(season["year"]))
        for name in (only or sheets.TABLE_TABS):
            table = tables[name]
            print("  {:<20} {:>5} rows x {:>2} cols".format(
                name, len(table.rows), len(table.columns)))
            if table.rows:
                print("      first slug  {}".format(table.rows[0]["slug"]))
                print("      last slug   {}".format(table.rows[-1]["slug"]))
        print("\n  --csv       write them to exports/cms/ to look at")
        print("  --live      push them to the Sheet")
        print("  --only=a,b  restrict to some tables")
        return

    failures = []
    for result in sheets.push_tables(
            season, only=only,
            allow_correction="--allow-correction" in argv):
        if result.get("error"):
            failures.append(result)
            print("  {:<20} REFUSED".format(result["tab"]))
            continue
        # `unchanged` is the number that matters on a frozen table: it means
        # the rows already published were replayed and not one of them moved.
        parts = ["+{} new".format(result.get("added", 0))]
        if result.get("unchanged"):
            parts.append("{} unchanged".format(result["unchanged"]))
        # A fill is a frozen row's blank cell learning its answer -- picks.correct
        # once a game is played. It counts inside `updated`, but it is reported
        # on its own because it is the one rewrite a frozen table accepts
        # without being asked, and folding it into "updated" would read as a
        # correction every single week.
        filled = result.get("filled", 0)
        if filled:
            parts.append("{} filled in".format(filled))
        if result.get("updated", 0) - filled:
            parts.append("{} updated".format(result["updated"] - filled))
        if result.get("protected"):
            parts.append("{} left alone".format(result["protected"]))
        if result.get("corrected"):
            parts.append("{} CORRECTED".format(len(result["corrected"])))
        print("  {:<20} {}  ({} total{})".format(
            result.get("tab", "?"), ", ".join(parts), result.get("total", 0),
            ", frozen" if result.get("frozen") else ""))

    if failures:
        print("\n{} table(s) were refused and nothing was written to them:\n"
              .format(len(failures)))
        for failure in failures:
            print("  {}".format(failure["tab"]))
            print("     {}\n".format(failure["error"].replace(
                "Apps Script refused the write: ", "")))
        sys.exit("Fix these and re-run. The tables above are unchanged.")


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


def _read_pick_csv(path, games):
    """Both shapes the picks ever arrive in.

    A row per competitor:   Name,PointsGuess,G1..G17
    A column per competitor (what the Google Form export parses into):
        header row of names, then one row per game, then a row of points guesses.

    A competitor with an empty column has not submitted yet and is skipped
    rather than loaded as a half sheet.
    """
    import csv
    with open(path) as fh:
        rows = [[cell.strip() for cell in row] for row in csv.reader(fh)]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        raise engine.SeasonError("{} is empty".format(path))

    def wl(cell):
        return cell.upper()[:1] if cell else ""

    # Transposed if the first cell under the header is a pick rather than a
    # points guess.
    transposed = len(rows) > 1 and wl(rows[1][0]) in ("W", "L")

    picks, guesses = {}, {}
    if transposed:
        names = rows[0]
        body = rows[1:]
        if len(body) < games + 1:
            raise engine.SeasonError(
                "expected {} game rows plus a points row, got {}".format(games, len(body)))
        for column, name in enumerate(names):
            if not name:
                continue
            sheet = [wl(row[column]) if column < len(row) else "" for row in body[:games]]
            total = body[games][column] if column < len(body[games]) else ""
            if not any(sheet) and not total:
                continue  # column reserved, nothing submitted
            picks[name] = sheet
            guesses[name] = int(float(total)) if total else None
    else:
        for row in rows:
            if row[0].lower() in ("competitor", "name"):
                continue
            picks[row[0]] = [wl(cell) for cell in row[2:2 + games]]
            guesses[row[0]] = int(float(row[1])) if len(row) > 1 and row[1] else None
    return picks, guesses


def cmd_picks(argv):
    """Load picks from a CSV, in either layout, and merge them into the season."""
    if not argv:
        sys.exit("usage: python3 cli.py picks <file.csv>")
    season = _load()
    games = len(season["games"])
    picks, guesses = _read_pick_csv(argv[0], games)

    unknown = sorted(set(picks) - set(season["roster"]))
    if unknown:
        sys.exit("{} is not on the roster. The roster is {}.".format(
            ", ".join(unknown), ", ".join(season["roster"])))

    # Picks are made before week 1, so a sheet arriving after the season starts
    # is a mistake. Loading it anyway would give that person picks for weeks
    # already played and add them to collections an old newsletter had already
    # published, changing what a past week looks like.
    late = sorted(n for n in picks if not season["picks"].get(n))
    played = season_mod.games_played(season)
    if late and played and "--force" not in argv:
        sys.exit(
            "{} has no sheet on record and {} game(s) have been played.\n"
            "  Adding someone mid-season backdates them into weeks that were\n"
            "  already published. Use --force if this is a genuine late entry."
            .format(", ".join(late), played))
    missing_guess = sorted(n for n in picks if guesses.get(n) is None)
    if missing_guess:
        sys.exit("no points guess for {}".format(", ".join(missing_guess)))

    # Validate only what arrived, then merge. Partial submissions are normal in
    # September: the roster stays twelve names long and the competitors who have
    # not sent a sheet keep an empty one, which is what stops `board` and `week`
    # from running on an incomplete field.
    engine.validate(picks, season_mod.results(season), season_mod.weights(season),
                    season["division_indices"], guesses)
    season["picks"].update(picks)
    season["points_guess"].update(guesses)
    season_mod.save(season)

    outstanding = [n for n in season["roster"] if not season["picks"].get(n)]
    print("Loaded {} pick sheet(s) of {} games each.".format(len(picks), games))
    for name in season["roster"]:
        sheet = season["picks"].get(name)
        if not sheet:
            continue
        wins = sheet.count("W")
        div = sum(1 for i in season["division_indices"] if sheet[i] == "W")
        print("  {:<8} {}-{}   division {}-{}   {} points{}".format(
            name, wins, games - wins, div, len(season["division_indices"]) - div,
            season["points_guess"][name], "   (new)" if name in picks else ""))
    if outstanding:
        print("\nStill outstanding ({}): {}".format(
            len(outstanding), ", ".join(outstanding)))
        print("The board stays locked until all {} are in.".format(len(season["roster"])))


def _game_ref(season, text):
    """A game index, or an NFL week written as w5. Refuses a bye."""
    raw = str(text).strip().lower()
    if raw.startswith("w") and raw[1:].isdigit():
        week = int(raw[1:])
        index = season_mod.game_index_for_week(season, week)
        if index is None:
            sys.exit("Week {} has no game ({}).".format(
                week, "the bye" if season_mod.is_bye_week(season, week) else "not on the schedule"))
        return index
    if not raw.lstrip("-").isdigit():
        sys.exit("Which game? A game index (0..{}) or an NFL week like w5.".format(
            len(season["games"]) - 1))
    index = int(raw)
    if not 0 <= index < len(season["games"]):
        sys.exit("No game at index {}. The season has games 0..{}.".format(
            index, len(season["games"]) - 1))
    return index


OVERRIDE_FIELDS = {"result": "result", "weight": "weight", "points": "points_for"}


def _parse_override(field, text):
    """The value a field accepts, or a sentence about why not."""
    raw = str(text).strip()
    if field == "result":
        value = raw.upper()[:1]
        if value not in (engine.WIN, engine.LOSS, engine.TIE):
            sys.exit("A result is W, L or T. Got {!r}.".format(raw))
        return value
    if field == "weight":
        percent = raw.endswith("%")
        try:
            number = float(raw.rstrip("%"))
        except ValueError:
            sys.exit("A weight is the Eagles' win probability: 0.62, or 62%. Got {!r}.".format(raw))
        # 0.62 is a probability. 62% is a percent. A bare whole number above 1
        # (62) is taken as a percent too, since no probability looks like that.
        # A bare 1.5 is neither and is refused rather than guessed at: reading
        # it as 1.5% turned a typo into a 0.015 that nobody meant.
        if percent or (number > 1.0 and number == int(number)):
            number /= 100.0
        elif number > 1.0:
            sys.exit("A weight is 0.62 or 62%. {!r} is neither; say which you meant.".format(raw))
        if not 0.0 <= number <= 1.0:
            sys.exit("A weight must land between 0 and 1 (or 0% and 100%). Got {!r}.".format(raw))
        return round(number, 4)
    try:
        number = float(raw)
    except ValueError:
        sys.exit("Points are a whole number. Got {!r}.".format(raw))
    if number < 0 or number != int(number):
        sys.exit("Points are a whole, non-negative number. Got {!r}.".format(raw))
    return int(number)


def cmd_override(argv):
    """Pin a result, weight or score by hand, or hand it back to ESPN.

        python3 cli.py override 4 result L         game index 4
        python3 cli.py override w5 weight 62%      the week 5 game
        python3 cli.py override w5 points 24
        python3 cli.py override 4 result --clear   back to ESPN's answer

    A pinned field is marked manual and `refresh` never touches it again, so
    correcting a bad pull is safe and permanent. Until now that was true and
    unreachable: set_override had no caller, and the only way to use it was to
    edit the one file that cannot be regenerated, by hand, during a live week.
    """
    usage = ("usage: python3 cli.py override <game> <result|weight|points> <value>\n"
             "       python3 cli.py override <game> <field> --clear\n"
             "  <game> is a game index (0..16) or an NFL week like w5")
    if len(argv) < 3:
        sys.exit(usage)
    import copy
    season = _load()
    index = _game_ref(season, argv[0])
    field = argv[1].strip().lower()
    if field not in OVERRIDE_FIELDS:
        sys.exit("The field is result, weight or points. Got {!r}.\n{}".format(argv[1], usage))
    key = OVERRIDE_FIELDS[field]
    source_key = {"result": "result_source", "weight": "weight_source",
                  "points_for": "points_source"}[key]
    game = next(g for g in season["games"] if g["index"] == index)
    ready = season_mod.has_picks(season)
    before_board = season_mod.run(season) if ready else None
    before = game.get(key)

    if argv[2] == "--clear":
        if game.get(source_key) != "manual":
            sys.exit("Game {} ({}) has no manual {}; it is already ESPN's.".format(
                index, game["label"], field))
        # Take ESPN's value back, on a copy first. From the cache when there
        # is one, so this works offline; a stale cache says so in the change
        # list. Validated before it is kept: clearing a pinned result back to
        # unplayed while a pinned score stays behind is a season the engine
        # refuses, and this used to save it anyway.
        trial = copy.deepcopy(season)
        season_mod.clear_override(trial, index, key)
        season_mod.refresh(trial, force=False)
        if ready:
            try:
                engine.validate(trial["picks"], season_mod.results(trial),
                                season_mod.weights(trial), trial["division_indices"],
                                trial["points_guess"],
                                points_scored=season_mod.points_scored(trial))
            except engine.SeasonError as exc:
                hint = ("\n  Clear the points on this game first."
                        if key == "result" and game.get("points_source") == "manual" else "")
                sys.exit("Clearing the {} would leave the season inconsistent: {}{}".format(
                    field, exc, hint))
        season.clear()
        season.update(trial)
        game = next(g for g in season["games"] if g["index"] == index)
        for change in season.get("last_refresh_changes") or []:
            print("  espn: {}".format(change))
        after = game.get(key)
        print("Game {} ({}): {} {} -> {}, back to ESPN.".format(
            index, game["label"], field, before, after))
    else:
        value = _parse_override(field, argv[2])
        if ready:
            # Validate against the whole season before touching it: a result of
            # "A" with a score, a weight out of range, a score on a game that
            # is not played. engine.validate says which, in a sentence.
            trial = copy.deepcopy(season)
            season_mod.set_override(trial, index, key, value)
            engine.validate(trial["picks"], season_mod.results(trial),
                            season_mod.weights(trial), trial["division_indices"],
                            trial["points_guess"],
                            points_scored=season_mod.points_scored(trial))
        season_mod.set_override(season, index, key, value)
        print("Game {} ({}): {} {} -> {}  (manual; refresh will not undo it)".format(
            index, game["label"], field, before, value))

    week = game.get("nfl_week")
    if week is not None and season_mod.get_snapshot(season, week) is not None:
        print("  Week {} is already recorded. Its snapshot does not move on its own:\n"
              "  re-run it with  python3 cli.py week {} --correction \"why\"  to republish."
              .format(week, week))

    season_mod.save(season)
    if ready:
        after_board = season_mod.run(season)
        moves = sorted(((n, after_board.weighted[n] - before_board.weighted[n])
                        for n in after_board.order), key=lambda kv: -abs(kv[1]))
        moved = [(n, d) for n, d in moves if abs(d) >= 0.05][:4]
        if moved:
            print("  board: " + ", ".join("{} {:+.1f}".format(n, d) for n, d in moved))
        else:
            print("  board: unchanged")


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
    "cms": cmd_cms,
    "picks": cmd_picks,
    "override": cmd_override,
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
