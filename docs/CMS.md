# The CMS tables

Seven tables, built from the season file, written to a Google Sheet, read by
Framer. `fep/cms.py` builds them and is pure: a season goes in, seven tables
come out, nothing is fetched or written. The transport is separate on purpose,
so swapping Sheets for Framer's Server API later changes one file.

```bash
python3 cli.py cms                    # what would be written
python3 cli.py cms --csv             # write them to exports/cms/ to look at
python3 cli.py cms --live             # push to the Sheet
python3 cli.py cms --live --only=games,standings
```

## The rule

> **A row published in week N is identical in week N+1.**

Everything is derived from *recorded facts*, never recomputed. Standings come
out of the weekly snapshots, which freeze when taken, rather than from re-running
the engine, so changing the engine in 2029 cannot move a number the family read
in 2026.

`tests/test_cms.py` asserts this by replaying a full season and comparing every
frozen row against its first published version. `appsscript/test_code.js`
asserts the server side: a push for one season cannot rewrite another season's
rows even when it explicitly tries.

## The tables

Two conventions, both there to stop a component being bound to the wrong thing:

- **One column names the season, and it is called `season`.** It holds the year
  and doubles as the reference to `seasons`, whose slug is that year. There used
  to be a numeric `year` beside it, which was two names for one fact. `seasons`
  itself still has `year`, because there it is the row's own attribute rather
  than a pointer.
- **Colour lives only in `competitors`.** That table is the mapping. It was
  denormalised onto every picks and standings row, which meant changing somebody's
  colour would have to rewrite hundreds of otherwise frozen rows to take effect.
  Components read it through the `competitor` reference.

| Table | Slug | Rows/season | Changes |
|---|---|---|---|
| `seasons` | `2026` | 1 | weekly |
| `competitors` | `amir` | 12 | rarely |
| `competitor_seasons` | `2026-amir` | 12 | weekly |
| `games` | `2026-w01` | 18 | **weekly** |
| `weeks` | `2026-w03` | 19 | **frozen** |
| `picks` | `2026-w01-amir` | 216 | **once a season** |
| `standings` | `2026-w07-amir` | 228 | **frozen, append only** |

About 490 rows a season.

**`games` reads as a matchup.** `home_team` / `home_abbr` and `away_team` /
`away_abbr`, rather than an opponent plus a home-or-away flag, so a row can be
laid out without working out which side the Eagles are on. Which side that is
comes from ESPN's recorded `home` flag, not from the "vs." or "@" in the label,
which is wrong for a neutral-site game: the 2026 Jaguars game in London reads
`Jaguars (JAX)` at home and `Eagles (PHI)` away. Abbreviations are ESPN's, which
is why Philadelphia is `PHI`.

**Every NFL week gets a row in `games` and in `picks`, including the bye**,
marked `is_bye`, with both teams blank and no pick. A bye is a week with no
matchup rather than a week that does not exist, and leaving it out put a hole in
any schedule or grid laid out from these tables. That is why a 17-game season
has 18 `games` rows and 216 `picks` rows.

**`games` holds current state on purpose.** A result genuinely becomes known
partway through the season, so this table changes. Anything that needs the
season *as it stood* in a given week reads `weeks` or `standings`, which are
per-week and frozen. That distinction is the entire reason `weeks` exists, and
it is the difference between this and the old per-week tabs that filtered a live
master sheet.

**`picks` has no `correct` column, deliberately.** Adding one would mean
rewriting all 204 rows every week as results land, turning a write-once table
into a weekly one for nothing. A component compares `pick` against the linked
game's `result` instead.

## Slugs

Every slug carries the year, because Framer upserts on slug: without it, 2027
week 1 lands on top of 2026 week 1 and the old row is gone. Weeks are zero
padded (`w07`) so a lexical sort is chronological.

**A slug never contains a value that can be corrected.** It used to carry the
opponent (`2026-w01-commanders`), which read nicely and was wrong: correcting one
team name in ESPN's data changed the slug, so the corrected row published as a
*new* row and the original was orphaned forever, because the transport never
deletes. Season and week cannot be corrected, so that is all a slug holds.

`competitors` is the one table whose slugs have no year, because a person spans
seasons. It is also the one table the Apps Script allows a push to rewrite
across years, and so the fourth table outside the invariant.

## What a spreadsheet does to a value

Sheets infers a format from what it sees, keeps that format when the contents
are cleared, and then applies it to whatever is written next. Both halves of
that bit us:

- `eagles_record` as `"5-2"` was stored as the 5th of February. It is `wins`
  and `losses` as integers now, and a test scans every cell of every table for
  anything Sheets would read as a date or a time.
- Clearing that column's contents left its *date format* behind, so the integer
  `4` written into it came back as `1900-01-03`.

So `writeTable` now pins each column's format before it reads: plain text where
the data is text, General everywhere else, so numbers stay numbers and booleans
stay booleans. It runs before the read, not just before the write, so a column
that is already mangled is read back as what it actually holds.

## Two seasons in one sheet

2025 was rebuilt as a season file (`scripts/backfill_2025.py`) so the tables
have a real season in them before 2026 starts: 19 weekly boards, 228 standings
rows, real names, real colours, real eliminations. Push it first, then 2026.

```bash
FEP_YEAR=2025 python3 cli.py cms --live
python3 cli.py cms --live
```

The second push is the first real test of the past-season guard: every 2025 row
must come back reported as `left alone`, not `updated`.

The weekly boards stored for 2025 are the ones that were **published**, not
recomputed. Recomputing them today drifts by up to 6.7 points in mid-season,
because ESPN's win probabilities moved during the year and only the final ones
were kept. The season file is stamped `reconstructed` and every snapshot carries
the caveat, so nothing downstream mistakes it for a contemporaneous record.

## Setup

Put the tables in **their own spreadsheet**, separate from the one published
newsletters still read. Nothing then shares a document with the old data.

1. New Google Sheet. Extensions > Apps Script, paste `appsscript/Code.gs`.
2. Project Settings > Script properties: `FEP_TOKEN` = a token from
   `python3 cli.py token`.
3. Deploy > New deployment > Web app, Execute as **Me**, access **Anyone with
   the link**. Copy the `/exec` URL.
4. Add it to `credentials/appsscript.json` as `cms_url` and `cms_token`:

```json
{
  "url": "https://script.google.com/macros/s/.../exec",
  "token": "the legacy sheet's token",
  "cms_url": "https://script.google.com/macros/s/.../exec",
  "cms_token": "the new sheet's token"
}
```

If `cms_url` is absent the push is refused rather than falling back to the
legacy deployment, which would put these tables in the spreadsheet the published
newsletters read. `--same-sheet` overrides that, for anyone who genuinely wants
them together.

The tabs do not need to exist. `writeTable` creates them, writes the header, and
refuses to write under a header that has drifted.

## Keeping the deployment in step

Editing `Code.gs` in the Apps Script editor does **not** redeploy it: a web app
serves the code from its deployed version, so the file here and the code
actually running can differ with nothing to show for it. That happened twice,
once silently rewriting rows that a newer guard would have refused.

So `Code.gs` carries a `CODE_VERSION`, the client reads the same constant from
its local copy, and a push refuses outright when they disagree:

```
Error: the deployment is running an older version (no version stamp)
but this checkout is 2026.09.07-a.
```

To redeploy: paste `appsscript/Code.gs`, save, then **Deploy > Manage
deployments > edit > Version: New version**. Editing an existing deployment
keeps the URL; a *new* deployment gives you a different one, which then has to
go into `credentials/appsscript.json`.

## Frozen tables, and correcting one

`weeks`, `standings` and `picks` hold a record of a week that has happened. Once
a row is written there, the only rewrite the script accepts is an identical one.
Replaying a week is a no-op; a week that has *changed* is refused, and the
refusal names the columns that moved.

That means re-running a past week will fail rather than quietly republish it:

```
standings is a frozen table and 12 row(s) would change:
2026-w03-amir (weighted: "18.6" -> "17.2"), ... Nothing was written.
```

Almost always that is the right answer, because ESPN's win probabilities move
and a re-run of week 3 in week 8 does not reproduce week 3. If the change really
is a correction, ask for it explicitly:

```bash
python3 cli.py cms --live --allow-correction
```

The response then lists every row it changed.

## What the script will not do

Even holding the URL and the token, a caller cannot:

- write to any tab outside the seven above, so `Weighted - MASTER` and the
  per-week tabs are unreachable
- push without naming the season, or send a row belonging to a season other
  than the one named. Both were bypasses: the guard used to take the season
  from the caller and believe it
- modify a row belonging to a season other than the one being pushed
  (`competitors` excepted, which spans seasons by design)
- change an already-written row in a frozen table without `allowCorrection`
- delete a row, ever
- write a string that looks like a formula (`=`, `+` or `-` leading a *string*;
  `@` is allowed, because every away game label begins with it, and only `=`
  actually creates a formula through the Sheets API)
- write under a header that does not match what it sent

Set an `ACTIVE_SEASON` script property to lock the sheet to one season: any push
for a different year is then refused outright. Leave it unset for no extra
restriction.

Run `node appsscript/test_code.js` to see all of those enforced.

## Driving the home screen from one value

The home screen toggles between standings, the chart, and the picks table, all
showing the same week. Framer's Dynamic Filters bind a page variable to a
Collection List filter, so this needs exactly one thing from the data: a single
field, with the same name and the same value, on every table involved.

That field is **`week_ref`**, and it holds a `weeks` slug:

```
2026-w07
```

| List | Collection | Filter |
|---|---|---|
| Standings | `standings` | `week_ref` is `{week}` |
| Picks table | `picks` | `week_ref` is `{week}` |
| This week's game | `games` | `week_ref` is `{week}` |
| Header, record, leader | `weeks` | `slug` is `{week}` |

One variable, four lists, one string to change. `2026-w07` selects twelve
standings rows, twelve picks, and one game. A bye week selects twelve standings
rows and no game, which is correct rather than an error.

The full-season picks grid is the same table with a different filter:
`season is 2026` gives all 204 rows.

`seasons.current_week` is there if you want the variable to default to the live
week rather than being typed. Newsletter pages do not need any of this: a CMS
page for a `weeks` item filters its lists by reference to the current item.
