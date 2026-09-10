#!/usr/bin/env python3
"""Rebuild 2025 as a season file, so the CMS tables have a real season in them.

    python3 scripts/backfill_2025.py [--write]
    python3 scripts/backfill_2025.py --capture   (refresh the fixture)

WHERE EACH FACT COMES FROM

    picks, points guesses, weights   ../2025/simulator.py, the canonical archive
    schedule, results, scores        ESPN, cross-checked against the archive
    the weekly weighted boards       chart-data/2025/week-NN.json, as published

Two of those three are outside this repository: the archive lives a directory
up, and ESPN is a live service that will not serve a 2025 predictor line
forever. So --capture writes both into data/fixtures/2025_source.json, with a
hash of the archive it read, and an ordinary run works offline from that. The
result is that anyone with a clone can rebuild 2025 and get the same file,
which is the difference between a reproducible artefact and one that happened
to exist on one laptop.

The weekly boards are taken from what was published rather than recomputed.
That matters: they are what the family actually saw, and recomputing them today
would produce slightly different numbers, because ESPN's win probabilities moved
during the season and only the final ones were kept. Recomputing would also
quietly violate the rule the whole CMS design rests on, that a published row
never changes.

WHAT IS EXACT AND WHAT IS NOT

    weighted            exact, taken from the published boards
    straight            exact, it does not depend on win probabilities
    current_points      exact, picks against results
    remaining_outcomes  exact
    deciding            approximate: a share of probability, so it uses the
                        final weights rather than that week's
    weights             the final ones, on every snapshot

Every snapshot is stamped `reconstructed` and carries that caveat, so nothing
downstream can mistake it for a contemporaneous record.
"""

from __future__ import annotations

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fep import chart, engine, espn, season as season_mod  # noqa: E402

# The archive now lives in the repo as a frozen test fixture, byte-identical to
# the sibling year folder it used to be read from. Same file, same sha256, and
# a --capture run no longer depends on what is next to the repo.
ARCHIVE = os.path.join(ROOT, "tests", "fixtures", "simulator_2025.py")
CHART_DATA = os.path.join(ROOT, "chart-data", "2025")
FIXTURE = os.path.join(ROOT, "data", "fixtures", "2025_source.json")
YEAR = 2025

CAVEAT = ("weighted boards as published; deciding and weights use the final "
          "ESPN lines because in-season lines were not kept")


def archive_literals() -> dict:
    """Pull the data out of simulator.py without running it.

    The module simulates and prints at import time, so it cannot simply be
    imported. Parsing the literals is also a better audit trail: it fails loudly
    if the archive is ever edited into a different shape.
    """
    with open(ARCHIVE) as fh:
        tree = ast.parse(fh.read())
    wanted = {"picks_dict", "predicted_points", "weight", "eagles_results",
              "division_weeks"}
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                found[target.id] = ast.literal_eval(node.value)
    missing = wanted - set(found)
    if missing:
        raise SystemExit("{} no longer defines {}".format(
            ARCHIVE, ", ".join(sorted(missing))))
    return found


def capture() -> dict:
    """Read the archive and ESPN once, and write down what they said."""
    import hashlib

    with open(ARCHIVE, "rb") as fh:
        raw = fh.read()
    archive = archive_literals()
    games = espn.fetch_schedule(YEAR)
    fixture = {
        "note": ("Captured so 2025 can be rebuilt without the sibling archive "
                 "or a live ESPN. Refresh with --capture."),
        "captured_from": os.path.relpath(ARCHIVE, ROOT),
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "archive": archive,
        "games": games,
    }
    directory = os.path.dirname(FIXTURE)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(FIXTURE, "w") as fh:
        json.dump(fixture, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote {}".format(os.path.relpath(FIXTURE, ROOT)))
    print("  archive sha256 {}".format(fixture["archive_sha256"][:16]))
    print("  {} games from ESPN".format(len(games)))
    return fixture


def sources() -> dict:
    """The fixture, or the live sources if there is no fixture yet."""
    if os.path.exists(FIXTURE):
        with open(FIXTURE) as fh:
            fixture = json.load(fh)
        # JSON has no integer keys, so the weight map comes back keyed by
        # string and sorted() then orders it 0, 1, 10, 11, 12, ... 2, 3. That
        # silently reordered the win probabilities and moved every board.
        fixture["archive"]["weight"] = {
            int(index): value
            for index, value in fixture["archive"]["weight"].items()
        }
        print("  reading data/fixtures/2025_source.json "
              "(archive {})".format(fixture["archive_sha256"][:12]))
        return fixture
    print("  no fixture; reading the archive and ESPN directly")
    return {"archive": archive_literals(), "games": espn.fetch_schedule(YEAR)}


def published_boards() -> dict:
    """{week: {Name: pct}} exactly as it went out."""
    final = json.load(open(os.path.join(CHART_DATA, "week-18.json")))
    boards = {}
    for entry in final["series"]:
        for week, value in zip(final["weeks"], entry["values"]):
            boards.setdefault(week, {})[entry["name"]] = value
    return boards


def build(write: bool = False) -> dict:
    source = sources()
    archive = source["archive"]
    picks = {name.capitalize(): list(sheet)
             for name, sheet in archive["picks_dict"].items()}
    guesses = {name.capitalize(): value
               for name, value in archive["predicted_points"].items()}
    weights = [archive["weight"][i] for i in sorted(archive["weight"])]
    roster = sorted(picks)

    games = [dict(g) for g in source["games"]]
    if len(games) != len(archive["eagles_results"]):
        raise SystemExit("ESPN has {} games, the archive has {}".format(
            len(games), len(archive["eagles_results"])))

    # Cross-check rather than trust. Two independent records of the same season
    # should agree, and if they do not, that is worth stopping for.
    for game, expected in zip(games, archive["eagles_results"]):
        if game["result"] != expected:
            raise SystemExit(
                "game {} ({}): ESPN says {}, the archive says {}".format(
                    game["index"], game["label"], game["result"], expected))

    espn_division = [g["index"] for g in games if g["division"]]
    if espn_division != archive["division_weeks"]:
        print("  note: division games differ. ESPN {}, archive {}. Using the "
              "archive, which is what the published boards used."
              .format(espn_division, archive["division_weeks"]))

    for game, weight in zip(games, weights):
        game["weight"] = weight
        game["weight_source"] = "archive"
        game["result_source"] = "espn"

    boards = published_boards()
    season = {
        "year": YEAR,
        "roster": roster,
        "picks": picks,
        "points_guess": guesses,
        "colors": chart.colors_for(roster),
        "games": games,
        "division_indices": archive["division_weeks"],
        "week_to_game_index": {str(w): i for w, i in
                               espn.week_to_game_index(games).items()},
        "bye_week": espn.bye_week(games),
        "bye_weeks": espn.bye_weeks(games),
        "snapshots": [],
        "sheet": dict(season_mod.DEFAULT_SHEET),
        "model": dict(season_mod.DEFAULT_MODEL),
        "reconstructed": True,
        "reconstruction_note": CAVEAT,
    }

    drift = []
    for week in sorted(boards):
        board = season_mod.run(season, through_week=week)
        entry = season_mod.snapshot(season, week, board, note=CAVEAT)
        recomputed = dict(entry["weighted"])
        # The published board is the fact. Keep the recomputed one beside it so
        # the size of the difference is visible rather than hidden.
        entry["weighted"] = dict(boards[week])
        entry["weighted_recomputed"] = recomputed
        entry["reconstructed"] = True
        worst = max((abs(recomputed[n] - boards[week][n]) for n in boards[week]),
                    default=0.0)
        drift.append((week, worst))

    print("\n{} rebuilt: {} games, {} competitors, {} weekly boards".format(
        YEAR, len(games), len(roster), len(season["snapshots"])))
    record = [g["result"] for g in games]
    print("  Eagles {}-{}, {} points".format(
        record.count("W"), record.count("L"),
        sum(g["points_for"] or 0 for g in games)))
    print("  bye week {}".format(season["bye_week"]))

    print("\n  how far a recompute drifts from what was published:")
    for week, worst in drift:
        bar = "#" * int(round(worst))
        print("    week {:>2}  {:>5.1f} pts  {}".format(week, worst, bar))
    print("  (the published values are what is stored; this only shows why)")

    final_correct = season["snapshots"][-1]["current_points"]
    champion = max(final_correct, key=lambda n: (final_correct[n], n))
    print("\n  final correct picks: {} on {} (Pop should lead on 11)".format(
        champion, final_correct[champion]))

    if write:
        path = season_mod.path_for(YEAR)
        season_mod.save(season)
        print("\n  wrote {}".format(os.path.relpath(path, ROOT)))
    else:
        print("\n  dry run. Pass --write to save it.")
    return season


if __name__ == "__main__":
    if "--capture" in sys.argv:
        capture()
    build(write="--write" in sys.argv)
