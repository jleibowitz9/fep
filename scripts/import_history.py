#!/usr/bin/env python3
"""Bring the historical record into the repo, once.

    python3 scripts/import_history.py

Until now `fep/history.py` read ten seasons from two places outside this
directory: six CSVs in the fep-master skill's data folder, and -- for 2024 and
2025 -- Jacob's old simulator scripts, parsed as source text out of the sibling
year folders.

Both were silent failure modes. A checkout anywhere else lost several seasons
and reported it as the record book disagreeing with itself, which reads like a
data corruption bug rather than a missing path. Parsing a Python file to get
picks out of it is also one refactor away from breaking.

This script copies the CSVs in and converts the two scraped seasons into rows
of the same CSV, so afterwards every season comes from one file in the repo and
the scraping code can be deleted.

It is written to be reproducible rather than clever: run it against the old
sources and it produces the same bytes, so its output can be checked rather
than trusted.
"""

from __future__ import annotations

import csv
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DEST = os.path.join(ROOT, "data", "history")

# The six files history.py actually reads. The skill's data folder holds a few
# more; they are working files for the newsletter, not inputs to the model.
CSVS = [
    "all_time_totals.csv",
    "champions_by_season.csv",
    "season_2024_weekly.csv",
    "season_2025_weekly.csv",
    "season_results_by_competitor.csv",
    "weekly_picks_all_seasons.csv",
]

PICKS = "weekly_picks_all_seasons.csv"
COLUMNS = ["Year", "Week", "Opponent", "Result", "Competitor", "Pick",
           "Correct", "RealWorldNote"]

# Jacob's 2024 sheet was left unfinished: the last two games are still 'A'. The
# results came from ESPN, which is authoritative for what actually happened.
# That was a runtime note; now that the rows are stored it belongs on the rows.
UNFINISHED_2024 = {17, 18}
ESPN_NOTE = "Result from ESPN; the 2024 sheet was left unfinished."


def source_dir() -> str:
    from fep import history
    return history.DEFAULT_DATA_DIR


def copy_csvs(src: str) -> None:
    os.makedirs(DEST, exist_ok=True)
    for name in CSVS:
        shutil.copy2(os.path.join(src, name), os.path.join(DEST, name))
        print("  copied {}".format(name))


def scraped_rows() -> list:
    """2024 and 2025, flattened into the same shape as every other season.

    Read through history.weekly_picks() rather than the parser directly, so the
    rows written are exactly the ones the rest of the code has been using.
    """
    from fep import history

    rows = []
    seasons = history.weekly_picks()
    for year in (2024, 2025):
        season = seasons[year]
        weeks = season["weeks"]
        for i, week in enumerate(weeks):
            opponent = season["opponents"][i]
            result = season["results"][i]
            note = ESPN_NOTE if year == 2024 and week in UNFINISHED_2024 else ""
            for name in sorted(season["picks"]):
                pick = season["picks"][name][i]
                rows.append({
                    "Year": year, "Week": week, "Opponent": opponent,
                    "Result": result, "Competitor": name, "Pick": pick,
                    "Correct": 1 if pick == result else 0,
                    "RealWorldNote": note,
                })
    return rows


def append_scraped(rows: list) -> None:
    path = os.path.join(DEST, PICKS)
    with open(path) as fh:
        existing = [l for l in fh if not l.startswith("#")]
    present = {r["Year"] for r in csv.DictReader(list(existing))}
    if "2024" in present or "2025" in present:
        raise SystemExit("2024/2025 are already in {}; nothing to do".format(PICKS))

    header = (
        "# Game-by-game picks, 2016 to 2025.\n"
        "#\n"
        "# 2016 to 2023 came from the family's own record. 2024 and 2025 were\n"
        "# reconstructed from Jacob's simulator scripts by\n"
        "# scripts/import_history.py; opponents, weeks and any result the sheet\n"
        "# never recorded come from ESPN.\n"
    )
    with open(path, "w", newline="") as fh:
        fh.write(header)
        fh.writelines(existing)
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        for row in rows:
            writer.writerow(row)
    print("  appended {} rows for 2024 and 2025".format(len(rows)))


def main() -> None:
    src = source_dir()
    if os.path.abspath(src) == os.path.abspath(DEST):
        raise SystemExit("history.py already points at the repo; already migrated")
    if not os.path.isdir(src):
        raise SystemExit("cannot find the source data at {}".format(src))

    print("from {}".format(src))
    print("to   {}\n".format(DEST))
    rows = scraped_rows()          # read before copying, while the old paths still work
    copy_csvs(src)
    append_scraped(rows)
    print("\nNow repoint history.DEFAULT_DATA_DIR at data/history and delete the "
          "simulator scraping.")


if __name__ == "__main__":
    main()
