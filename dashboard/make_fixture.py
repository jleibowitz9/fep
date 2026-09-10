#!/usr/bin/env python3
"""
Generate the synthetic front-end fixture, `sample-data.json`.

    python3 dashboard/make_fixture.py                  # rewrite sample-data.json
    python3 dashboard/make_fixture.py --week 12        # a different week
    python3 dashboard/make_fixture.py --check          # verify it is reproducible
    python3 dashboard/make_fixture.py --refresh-inputs # re-freeze the inputs

WHY THIS EXISTS
---------------
The fixture is a full dashboard payload for a week that has not happened, so the
front end can be worked on out of season. It used to be a committed blob with no
recorded provenance, which caused two problems.

First, it was easy to read as a real observed snapshot. It carried a `generated`
date of 2026-09-03 alongside final results for games dated 13 September through
27 October, which is only coherent once you know it is invented.

Second, and worse, nothing tied its shape to `collect()`. The fixture carried a
`whatif` key that `collect()` did not produce, so the What If tab worked against
the mock and reported "No precomputed board" against every live build. A payload
the real builder cannot produce hides exactly the bugs a fixture is supposed to
catch, so this script derives the fixture FROM `collect()` and then plays a
season forward into it. Anything `collect()` stops emitting disappears here too.

The results are drawn from the ESPN win probabilities with a fixed seed, so the
file is reproducible: same seed, same fixture, byte for byte.

WHY THE INPUTS ARE FROZEN
-------------------------
That reproducibility was a fiction for as long as this read the live season
file. Two things underneath it move. Pick sheets arrive through the season, so
a fixture generated in August and checked in September is built from different
picks. And `refresh` pulls new ESPN weights every week, and the seeded coin
flips are `rng.random() < weight` -- so the check broke on a schedule, roughly
every Sunday, no matter how recently it had been regenerated.

So the inputs are frozen into `fixture_season.json` beside this script: the
schedule, the roster, the colours, and weights as they stood when it was
written. Picks and points guesses are generated from the seed and never copied
from live participation, because a synthetic season should not contain twelve
real people's actual predictions. `--refresh-inputs` re-freezes deliberately,
which is a thing to do for a new season and not otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

OUTPUT = os.path.join(HERE, "sample-data.json")
INPUTS = os.path.join(HERE, "fixture_season.json")
SEED = 2026

# What the fixture takes from a season. Everything here is schedule or
# presentation; nothing in it changes on its own between two runs of --check.
# `picks`, `points_guess` and `snapshots` are deliberately absent: the fixture
# invents its own, so no real participation reaches it.
FROZEN_INPUT_FIELDS = (
    "year", "roster", "colors", "games", "division_indices",
    "week_to_game_index", "bye_week", "bye_weeks", "sheet", "model",
)


def freeze_inputs(year: int, path: str = INPUTS) -> str:
    """Take the schedule and roster out of the live season file, once."""
    from fep import season as season_mod

    live = season_mod.load(year)
    frozen = {field: live[field] for field in FROZEN_INPUT_FIELDS if field in live}
    frozen["frozen_from"] = "data/season_{}.json".format(year)
    frozen["note"] = ("Inputs for dashboard/make_fixture.py, frozen so the "
                      "fixture does not change when picks arrive or ESPN moves "
                      "a line. Refresh with --refresh-inputs.")
    with open(path, "w") as fh:
        json.dump(frozen, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return path


def frozen_inputs(year: int, path: str = INPUTS) -> dict:
    """The frozen season inputs, or the live file if none have been frozen yet."""
    from fep import season as season_mod

    if not os.path.exists(path):
        return season_mod.load(year)
    with open(path) as fh:
        season = json.load(fh)
    # A fixture needs the keys a season has, even the ones it fills in itself.
    season.setdefault("picks", {})
    season.setdefault("points_guess", {})
    season.setdefault("snapshots", [])
    return season


def synthetic_season(year: int, week: int, seed: int = SEED) -> dict:
    """The frozen season inputs, played forward through `week` with a fixed seed."""
    from fep import season as season_mod

    season = frozen_inputs(year)
    rng = random.Random(seed)
    games = len(season["games"])

    # Every sheet is invented. The frozen inputs carry no picks at all, and that
    # is on purpose twice over: it keeps twelve real people's actual predictions
    # out of a synthetic season, and it stops the fixture changing shape as real
    # sheets arrive through September.
    for name in season["roster"]:
        sheet = season["picks"].get(name) or []
        if len(sheet) != games:
            season["picks"][name] = [
                "W" if rng.random() < float(g["weight"]) else "L"
                for g in season["games"]
            ]
        if season["points_guess"].get(name) is None:
            season["points_guess"][name] = rng.randrange(370, 460)

    for game in season["games"]:
        if game["nfl_week"] > week:
            continue
        weight = game["weight"]
        # Roll the actual ESPN number, so the invented season is at least a
        # plausible draw from the model the dashboard is displaying.
        game["result"] = "W" if rng.random() < float(weight) else "L"
        # Eagles scoring, loosely: more when they win.
        base = 27 if game["result"] == "W" else 17
        game["points_for"] = max(0, int(rng.gauss(base, 6)))
        game["result_source"] = "synthetic"

    # Snapshots are what the sparklines, Heat Check and volatility read, so the
    # fixture needs one per week up to the one being built.
    season["snapshots"] = []
    for w in range(0, week + 1):
        board = season_mod.run(season, through_week=w)
        season["snapshots"].append({
            "week": w,
            "weighted": {n: round(board.weighted[n], 1) for n in board.order},
            "current_points": dict(board.current_points),
            "deciding": {k: round(v, 1) for k, v in board.deciding.items()},
            "remaining_outcomes": board.remaining_outcomes,
        })
    return season


def build_fixture(year: int = 2026, week: int = 7, seed: int = SEED) -> dict:
    """A payload with exactly the shape `collect()` produces."""
    import build as build_mod
    from fep import season as season_mod

    season = synthetic_season(year, week, seed)

    # collect() reads the season off disk, so hand it this one instead. Going
    # through collect() rather than assembling the payload here is the whole
    # point: the fixture cannot drift from the live contract.
    real_load = season_mod.load
    season_mod.load = lambda y: season
    try:
        data = build_mod.collect(year, week)
    finally:
        season_mod.load = real_load

    data["fixture"] = {
        "synthetic": True,
        "seed": seed,
        "note": ("Generated by dashboard/make_fixture.py. The results and scores "
                 "are invented, drawn from the real ESPN win probabilities with a "
                 "fixed seed. This is a future state of the {} season, not an "
                 "observed one.".format(year)),
    }
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--week", type=int, default=7)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="regenerate and compare, without writing")
    parser.add_argument("--refresh-inputs", action="store_true",
                        help="re-freeze the schedule and roster from the live "
                             "season file. A new-season thing, not a weekly one.")
    args = parser.parse_args()

    if args.refresh_inputs:
        path = freeze_inputs(args.year)
        print("Froze {} from the {} season file.".format(
            os.path.relpath(path, ROOT), args.year))
        print("Now rerun without --refresh-inputs to rebuild the fixture.")
        return 0

    data = build_fixture(args.year, args.week, args.seed)
    payload = json.dumps(data, indent=1, sort_keys=True) + "\n"

    if args.check:
        with open(args.out) as fh:
            current = fh.read()
        if current == payload:
            print("{} is reproducible".format(os.path.relpath(args.out, ROOT)))
            return 0
        print("{} does NOT match a fresh generation. Rerun without --check."
              .format(os.path.relpath(args.out, ROOT)))
        return 1

    with open(args.out, "w") as fh:
        fh.write(payload)
    print("Wrote {} ({:.0f} KB) -- {} week {}, seed {}".format(
        os.path.relpath(args.out, ROOT), os.path.getsize(args.out) / 1024,
        args.year, args.week, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
