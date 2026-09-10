# The historical record, 2016 to 2025

Six CSVs. `fep/history.py` reads them and nothing else, so every career stat,
head-to-head and "first time since" in a newsletter traces back to this folder.

| File | What it holds |
|---|---|
| `champions_by_season.csv` | one row per season: champion, winning score, Eagles record |
| `all_time_totals.csv` | career totals per competitor |
| `season_results_by_competitor.csv` | every finish, every season |
| `weekly_picks_all_seasons.csv` | game-by-game picks, all ten seasons |
| `season_2024_weekly.csv` | the 2024 weekly weighted board, as published |
| `season_2025_weekly.csv` | the 2025 weekly weighted board, as published |

## Where this came from

These used to live in the `fep-master` skill's data folder, down a path
containing two session UUIDs, and the 2024 and 2025 picks were not in any CSV
at all -- they were parsed out of Jacob's old simulator scripts as source text.

A checkout anywhere else silently lost seasons, and reported it as the record
book disagreeing with itself rather than as a missing file. That is a bad
failure: it reads like data corruption and sends you looking in the wrong
place. `scripts/import_history.py` brought everything in and can be re-run
against the old sources to reproduce these bytes.

`FEP_DATA_DIR` still overrides the location, so the skill can point at this
folder instead of keeping a second copy that drifts.

## Treat these as frozen

This is what the family actually saw. The quirks in it are real and are honoured
rather than cleaned up:

- **2016 Week 16** was really a win, and the family's sheet scored it a loss.
  Every 2016 total was computed against that loss, so the model stays faithful
  to it and flags the discrepancy.
- **2020 Week 3** was a tie that counted for nobody.
- **2024 weeks 17 and 18** were never filled in on Jacob's sheet; those results
  come from ESPN and each row says so.
- Three competitor-seasons state a total one off from their own pick grid.
  `history.KNOWN_TOTAL_QUIRKS` lists them, and the stated total wins.

If a number here looks wrong, that is a finding to record, not a cell to edit.
`history.reconcile_totals()` recomputes all 104 competitor-seasons from their
own pick grids and is the right place to start.
