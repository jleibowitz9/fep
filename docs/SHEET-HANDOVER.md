# Carrying the Sheet from one season to the next

## The constraint

Framer binds a collection to a specific tab, and every component is mapped to
that collection's fields. Make a new tab for 2026 and you inherit a remapping
job across the whole site. So the tab has to stay put and the season has to move
through it.

## What to do, in order

**1. Freeze 2025 into an archive tab.**

Right click `Weighted - MASTER` > **Duplicate**, rename the copy
`2025 - Weighted MASTER`. Then select the whole copy and
**Edit > Paste special > Values only** over itself.

The values-only step matters. A duplicate carries the placement formulas in
column N onward, and if any of them reference other tabs they would keep
pointing at the live ones and drift. Flattening to values makes the archive a
photograph rather than a live document.

Do the same for `Straight - MASTER` if you use it.

**2. Check what actually reads `Weighted - MASTER`.**

The moment 2026 week 0 is pushed, anything mapped to that tab shows 2026. The
eighteen `Weighted - W#` tabs are unaffected, which is the whole reason they
exist, so any published 2025 newsletter reading a per-week tab is safe. The
thing to check is whether the 2025 season recap page reads MASTER directly. If
it does, point it at `2025 - Weighted MASTER` before pushing.

**3. Push. There is no clearing step.**

```bash
python3 cli.py push          # dry run, prints the exact block
python3 cli.py push --live
```

Every push writes the entire `B2:M20` block, and a week with no snapshot is
written as a blank rather than skipped. So the first 2026 push puts week 0 in
row 2 and blanks rows 3 through 20 in the same call. There is no window where
the tab is half 2025 and half 2026, and no way to forget to clear it.

**4. Leave the 37 per-week tabs alone.**

They are what makes an old newsletter keep showing old data, and they cost
nothing. 2026 does not add to them: the chart now reads a frozen JSON file per
week from GitHub, which is the same immutability for one file instead of two
tabs and a component variant.

## The straight board

`sheet.straight_tab` in `data/season_2026.json` is null, so a push writes the
weighted board only. Set it to `"Straight - MASTER"` and one `push` keeps both
tabs in step, from the same snapshot, in the same run.

## What has not changed

Column A, and column N onward, are still never written. That is enforced in
`sheets.py` and independently in the Apps Script, and the script still refuses
any tab whose row 1 does not match the roster. Pointing a push at the wrong tab
fails rather than scribbling on it.
