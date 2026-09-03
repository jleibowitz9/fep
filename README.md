# FEP 2026

The Family Eagles Pool simulator, eleventh season.

Runs locally. Nothing is deployed, nothing is typed by hand, and every number
comes from the model or from ESPN.

## The weekly run

```bash
python3 cli.py week
```

That one command:

1. pulls the latest results, scores and ESPN matchup-predictor weights
2. runs the model, pinned to the end of that NFL week
3. saves a snapshot (so Heat Check has something to compare against)
4. writes the stat pack to `newsletters/week-NN/statpack.md`
5. renders the chart to `newsletters/week-NN/chart.html`
6. publishes `chart-data/2026/week-NN.json` for the Framer component

Then:

```bash
python3 cli.py push          # dry run: shows exactly what would be written
python3 cli.py push --live   # writes B2:M20 and nothing else
```

**You no longer read percentages off ESPN.** The matchup predictor's
`gameProjection` is the number you used to click through the site for, and it
comes down automatically for all 17 games.

## Setting up a season

```bash
python3 cli.py init                 # pulls the schedule, bye week and division games
python3 cli.py picks picks.csv      # loads the 12 pick sheets
```

`picks.csv` is one row per competitor: `Name,PointsGuess,G1,...,G17` with W or L.
Loading validates every sheet and refuses anything malformed, so a mis-pasted row
fails loudly instead of scoring against the wrong games.

For 2026 the schedule is 17 games with the **bye in Week 10**, and the six NFC
East games land at indices `[0, 6, 7, 8, 10, 16]`. Both were derived from ESPN,
not typed.

## Other commands

| Command | What it does |
|---|---|
| `cli.py board` | current board, no snapshot, no files written |
| `cli.py refresh` | pull from ESPN, preserving any manual overrides |
| `cli.py leverage` | every remaining game ranked by how much it swings the pool |
| `cli.py statpack [N]` | print a week's stat pack to the terminal |

## Where things live

| | |
|---|---|
| `data/season_2026.json` | **the only source of truth.** Picks, results, weights, scores, and one snapshot per week |
| `newsletters/week-NN/` | stat pack and chart for that week |
| `chart-data/2026/week-NN.json` | immutable per-week data for the Framer chart |
| `credentials/` | the service-account key, gitignored |
| `framer/` | the Framer code component and its setup notes |
| `docs/REVIEW-2026.md` | the algorithm review |

**Facts are stored. Statistics are not.** Leverage, heat check, differentiation
and the rest are recomputed on demand, because a cached statistic is one that can
silently disagree with the board after a result is corrected.

Every result, score and weight records whether it came from ESPN or from you.
Refreshing never overwrites a manual override, so it is always safe to run.

## Google Sheets, one-time setup

The push writes **only** the weekly competitor percentages, to `B2:M20`. It never
touches column A, and never touches column N or anything right of it where the
placement formulas live. It reads row 1 first and aborts if the headers do not
match the roster, rather than writing misaligned columns into a live site.

To enable it (free, no billing account, no credit card):

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create
   a project. Any name.
2. APIs and Services, then Library. Search for **Google Sheets API** and enable it.
3. APIs and Services, then Credentials. Create credentials, choose **Service
   account**. Any name, no roles needed.
4. Open the service account, go to **Keys**, Add key, Create new key, **JSON**.
   It downloads a file.
5. Save it as `credentials/service-account.json` in this folder. It is gitignored.
6. Open the JSON and copy the `client_email` value. It looks like
   `something@project-id.iam.gserviceaccount.com`.
7. Share your FEP Google Sheet with that address as an **Editor**, the same way
   you would share with a person.

Then verify against a copy before touching the real tab:

```bash
python3 cli.py push --tab="Scratch"        # dry run against a duplicate tab
python3 cli.py push --tab="Scratch" --live
```

If you never do this, everything else still works. `cli.py push` prints a
paste-ready block, and `fep/sheets.py` will hand you a CSV.

## The chart

See `framer/README.md`. Short version: one Framer code component, one `week`
number per newsletter. It replaces roughly 38 hidden sheet tabs and 19 component
variants, because each week's data is published as its own immutable file rather
than filtered out of a master sheet.

## Tests

```bash
python3 tests/test_engine.py
```

33 tests. The ones that matter:

- **the 2025 replay** must match Jacob's published boards exactly, or ten years
  of family history quietly changes
- **the tiebreaker cascade**, verified layer by layer, including the bug that
  was latent in 2025
- **the Sheet range guard**, which must refuse to touch column A or the
  placement formulas
- **no em dashes or en dashes** anywhere in the stat pack

## Requirements

The engine, the ESPN pull, the chart and the stat pack use only the standard
library, on the system Python 3.9. `requirements.txt` covers the two optional
extras: Google Sheets and the Streamlit dashboard.
