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
| `games` | `2026-w01-commanders` | 17 | **weekly** |
| `weeks` | `2026-w03` | 19 | **frozen** |
| `picks` | `2026-w01-commanders-amir` | 204 | **once a season** |
| `standings` | `2026-w07-amir` | 228 | **frozen, append only** |

About 490 rows a season.

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

`competitors` is the one table whose slugs have no year, because a person spans
seasons. It is also the one table the Apps Script allows a push to rewrite
across years.

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

If `cms_url` is absent the tables go to the same deployment as the legacy push,
which works but puts them in the old spreadsheet.

The tabs do not need to exist. `writeTable` creates them, writes the header, and
refuses to write under a header that has drifted.

## What the script will not do

Even holding the URL and the token, a caller cannot:

- write to any tab outside the seven above, so `Weighted - MASTER` and the
  per-week tabs are unreachable
- modify a row belonging to a season other than the one being pushed
  (`competitors` excepted, which spans seasons by design)
- delete a row, ever
- write a string that looks like a formula (`=`, `+`, `-`, `@` in a *string*; a
  negative number is a number and is fine)
- write under a header that does not match what it sent

Run `node appsscript/test_code.js` to see those enforced.

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
