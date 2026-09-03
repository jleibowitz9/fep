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
| `cli.py who <name>` | career record, picking personality, ready-made lines |
| `cli.py h2h <a> <b>` | head to head across every shared season |
| `cli.py retro <year>` | replay any season from 2016 on through the model |

## History

`fep/history.py` reads all ten seasons: the record book, career totals, and
game-by-game picks for 2016 through 2025. It exists so no number in a newsletter
is ever quoted from memory.

`cli.py retro <year>` replays a past season week by week and reconstructs the
drama those pre-newsletter years never got: when each competitor was
mathematically eliminated, when the lead changed, and how close it actually was.
2021, for instance, went to the final game with a three-way tie at 14.

Two honest caveats, both stated in the output:

- Historical ESPN win probabilities do not exist, so a replay treats every
  unplayed game as a coin flip. That is the **straight-up** board, not the
  weighted one.
- Points guesses were not recorded before 2024, so the third tiebreaker cannot
  be applied and anyone reaching it splits evenly.

The data has real quirks and the module surfaces rather than hides them: 2016's
Week 16 was really a win that the family scored as a loss (and every 2016 total
was computed against that loss), 2020 Week 3 was a tie that counted for nobody,
and `reconcile_totals()` recomputes all 104 competitor-seasons from their own
pick grids. 102 match exactly; the two that do not are single-cell source-sheet
quirks where the stated total is authoritative.

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

## Pushing to the Sheet

The push writes **only** the weekly competitor percentages, to `B2:M20`. It never
touches column A, and never touches column N or anything right of it where the
placement formulas live. It checks row 1 against the roster and aborts on a
mismatch rather than writing misaligned columns into a live site.

It goes through an **Apps Script web app that lives inside the spreadsheet**, so
there is no Google Cloud project, no service account and no key file to rotate.
That is not just convenience: service account key creation is blocked on this
account by the `iam.disableServiceAccountKeyCreation` organization policy, and an
Apps Script deployment runs as you and is not subject to it.

Setup is in **`appsscript/README.md`** and takes about five minutes. The short
version: paste `appsscript/Code.gs` into Extensions > Apps Script, run
`python3 cli.py token` for a secret, deploy as a web app, and save the URL and
token to `credentials/appsscript.json` (gitignored).

The same guards are enforced twice, in the Python client and again in the script
itself, because a guard that only exists on the caller is not a guard. The script
also rejects any cell that is not a number or blank, so a formula string cannot
be injected into the Sheet.

Until it is set up, `python3 cli.py push` prints a paste-ready block for cell B2.

## The chart

See `framer/README.md`. Short version: one Framer code component, one `week`
number per newsletter. It replaces roughly 38 hidden sheet tabs and 19 component
variants, because each week's data is published as its own immutable file rather
than filtered out of a master sheet.

## Tests

```bash
python3 tests/test_engine.py
```

44 tests. The ones that matter:

- **the 2025 replay** must match Jacob's published boards exactly, or ten years
  of family history quietly changes
- **the retro replay** must reproduce the right champion and the exact winning
  score for all ten seasons
- **the tiebreaker cascade**, verified layer by layer, including the bug that
  was latent in 2025
- **the Sheet range guard**, which must refuse to touch column A or the
  placement formulas
- **six NFC East games every season**, which is what catches an opponent-parsing
  slip in the historical data
- **no em dashes or en dashes** anywhere in the stat pack

## Requirements

The engine, the ESPN pull, the chart and the stat pack use only the standard
library, on the system Python 3.9. `requirements.txt` covers the two optional
extras: Google Sheets and the Streamlit dashboard.
