# Review brief: the CMS layer and supporting changes

Twelve commits, `ba4b378..HEAD`, about 2,500 lines. The centre of it is a new
module, `fep/cms.py`, and a new write path in `appsscript/Code.gs`.

## What this is for

The FEP website is built in Framer. Historically each week's standings were
preserved by duplicating a spreadsheet tab and a component variant per week,
roughly 37 tabs and 19 variants a season, all maintained by hand. Worse, those
per-week tabs are *live formulas* reading a master tab, so they do not actually
preserve anything: overwrite the master and all nineteen historical newsletters
silently change.

The replacement is seven CMS tables in a Google Sheet, synced to Framer
collections. `fep/cms.py` builds them from a season file; the transport is
separate so Framer's Server API can replace Sheets later without touching the
model.

## The invariant

> **A row published in week N must be identical in week N+1.**

This is the requirement, stated by the owner, and most of the design follows
from it. Anything that lets a past row change is a finding, however small.

The mechanism is that published rows are derived from **recorded facts**, never
recomputed. Standings come from the weekly snapshots frozen in the season file,
not from re-running the engine, so a future change to the model cannot move a
number the family already read.

Three tables hold current state deliberately and are *not* covered by the
invariant: `games` (a result becomes known), `seasons`, `competitor_seasons`.
Anything needing the season as it stood in a given week must read `weeks` or
`standings`. If you find a place that reads `games` for historical context, that
is a finding.

## Files, in rough order of importance

| File | What it is |
|---|---|
| `fep/cms.py` | new. Season in, seven tables out. Pure: no I/O, no globals |
| `appsscript/Code.gs` | `writeTable` added: upsert by slug, append only, past-season protection |
| `appsscript/test_code.js` | 16 guard tests against a stub of the Sheets API (`node appsscript/test_code.js`) |
| `tests/test_cms.py` | 30 tests, including the invariant replayed over a full season |
| `fep/sheets.py` | `push_tables`, `tables_to_csv`, separate CMS deployment config |
| `fep/chart.py` | colours keyed by name rather than roster index, palette extensible |
| `fep/season.py` | `snapshot()` now masks results to its own week; records `colors` |
| `fep/espn.py` | `bye_weeks()` (plural) for an eighteen-game season |
| `cli.py` | `cms` command; picks loader reads both CSV shapes and merges partial fields |
| `docs/CMS.md` | the schema and the conventions |

## Where I would attack it

Ordered by how likely I think a real problem is.

1. **`cms.py` immutability edge cases.** The invariant test replays a clean
   season. It does not cover: a result being *corrected* after the fact, a week
   being re-snapshotted, or a competitor being added mid-season. Are there
   inputs where a frozen row legitimately changes?
2. **`standings.change` and `rank`.** Both are computed across snapshots.
   `change` reads the previous snapshot in iteration order; if snapshots are ever
   out of order or a week is missing, is the value still correct or silently
   wrong? `_ranked` implements competition ranking by hand.
3. **The Apps Script, against a stub.** `appsscript/test_code.js` fakes
   `SpreadsheetApp`. Real behaviour differs: `getDataRange()` on an empty sheet,
   `insertSheet` defaults, row and column growth, the 6-minute execution limit,
   and payload size (`standings` reaches 228 rows x 13 columns). None of that is
   exercised. Treat the guard tests as necessary, not sufficient.
4. **`colors_for` determinism.** A newcomer's colour is stable once recorded in
   the season file, but the *first* assignment for several new names at once
   depends on roster order. Is there a path where a colour is assigned twice
   differently before being recorded?
5. **The `year` to `season` rename.** Every table used to carry both. Grep for
   stale readers. The Apps Script guard keyed on `year`; if that had been missed
   the past-season protection would have silently stopped working while every
   test still passed.
6. **`split_label`.** Parses ESPN's label string. I introduced and then fixed a
   bug here where `(@|at)\b` never matched `"@ Titans"` (no word boundary between
   two non-word characters) and reported every away game as home. Look for
   sibling cases: labels with no prefix, nested parentheses, unusual venues.
7. **`snapshot()` masking.** Changed to store results as of its own week rather
   than the season's current results. Check nothing else read that field
   expecting current state.
8. **`history.career` for a rookie.** `cms._career` swallows `HistoryError`.
   Is swallowing right, or does it hide a real lookup failure for an existing
   competitor whose name is misspelled?

## What is already covered, so it need not be re-reported

- 97 Python tests (`python3 -m pytest tests -q`), 16 Apps Script tests
- The invariant, replayed across a full 18-week season, per-row
- All 19 published 2025 chart files rebuilt from the finished season, byte
  identical, asserting no later result leaks backwards
- Past-season protection: a 2027 push that explicitly tries to overwrite a 2026
  row is refused and the 2026 value is unchanged
- An 18-game season with two byes; a 24-competitor field; a competitor leaving
- Tab allowlist, formula-string rejection, header drift, empty slug, short row,
  bad token, no truncation on a partial push
- Slug uniqueness within tables, and no collisions between 2026 and 2027

## Known limitations, deliberate

- **Weights cannot be masked to a past week.** ESPN publishes only the current
  line, so a backfilled week carries today's weights. Documented in
  `season.snapshot`.
- **Two Framer assumptions are untested**, and both would be caught the moment
  a collection is wired up: that a repeater can read a referenced item's fields
  (this is why `picks` has no `correct` column and no `color`), and that Dynamic
  Filters can drive several Collection Lists from one page variable.
- **Nothing has run against a real Google Sheet yet.** The CMS spreadsheet does
  not exist.

## Commit hygiene, one real issue

`1abb033` and `05c76b7` swept in uncommitted work from an earlier session
(`analytics.pin`, `analytics.whatif_boards`, and about 160 lines of
`dashboard/template.html`). Their commit messages describe the colour palette
change and the future-proofing tests, and say nothing about those files. Review
them on their merits rather than against the message. `analytics.pin` in
particular is substantive: it drops later snapshots as well as masking later
results, which fixed a Week 1 stat pack reporting Week 2's volatility.

## Running it

```bash
python3 -m pytest tests -q        # 97
node appsscript/test_code.js      # 16
python3 cli.py cms                # table shapes
python3 cli.py cms --csv          # exports/cms/*.csv, real 2026 data
```

The season file (`data/season_2026.json`) currently holds 7 of 12 pick sheets,
so `weeks` and `standings` are empty: they need a board, which needs the full
field. `tests/test_cms.py:build_season` constructs a complete synthetic season
without ESPN, which is how the invariant is tested.
