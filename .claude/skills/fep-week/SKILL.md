---
name: fep-week
description: The FEP weekly operating runbook - run the model after an Eagles game, check the board, publish the percentages to the Sheet and the CMS, and get the stat pack ready for the newsletter. Use this skill whenever the user says it is time to run the week, asks to update the board or the standings, mentions the weekly run, the Dock button, pushing to the Sheet, the CMS tables, the Framer chart, or asks why a number on the site does not match the dashboard. Also use it when a result or an ESPN weight is wrong and needs correcting by hand, or when a past week has to be rebuilt. Reach for this before running any cli.py command by hand, since the order the commands run in is what keeps the published history honest.
---

# The FEP week

One Eagles game happens, and a fixed sequence follows. The order matters: each
step reads what the previous one wrote, and two of them publish numbers the
family will read and cannot un-read.

For repo mechanics -- source of truth, generated files, testing, GitHub auth --
see the `fep-dev` skill. For newsletter *writing*, see `fep-master`.

## The normal week

Two icons do the same week, and which one to use depends on whether you want to
watch it happen or just have it done.

**The FEP icon** opens the dashboard as an application, and the week is the
button in its top right. The page stays open afterwards showing the board the
run produced, and the rest of the week -- the Sheet push, the CMS tables, a
late pick sheet -- is a button in its Build & share tab. This is the one to
reach for when there is any chance you will want to look at something or push
somewhere afterwards.

**The FEP Week icon** runs the week unattended in a Terminal window and opens
the finished dashboard at the end. Nothing to click, nothing to leave running.

Both do the same four things in order, and neither is doing them itself: they
run `cli.py`, which is the only implementation there is.

1. `cli.py week` -- pull results, scores and ESPN matchup-predictor weights,
   run the model pinned to that NFL week, freeze a snapshot, write the stat pack
   and chart, publish the week's chart data
2. `cli.py dashboard` -- rebuild the single-file dashboard
3. commit the season file and push it to GitHub
4. show the dashboard

A failed step stops the ones after it, so a run that could not finish is never
the run that gets committed and pushed. In the app the output of every step
appears in the page; in the Terminal window it waits for a keypress, so an
error cannot scroll past unread.

The equivalent by hand, if something needs doing step by step:

```bash
cd "$HOME/FEP Data Center/2026"
python3 cli.py week
python3 cli.py dashboard
```

## What to check before publishing

The run prints the board and the week-over-week deltas. Before pushing anything
outward, confirm:

- **The week is the one you meant.** `cli.py week` defaults to the current NFL
  week. Pass a number to rebuild an earlier one: `python3 cli.py week 7`.
- **The result came from ESPN, not a guess.** The run prints every change it
  pulled. The dashboard's data audit shows the provenance of all 17 games.
- **The deltas are explainable.** A competitor moving several points on a game
  they did not pick uniquely is worth a second look before it reaches the Sheet.

## Publishing outward

These two steps put numbers in front of the family. Both have dry runs. Use
them.

```bash
python3 cli.py push          # dry run: exactly what would be written
python3 cli.py push --live   # writes B2:M20, nothing else
```

The push writes only the weekly competitor percentages. It never touches column
A, and never column N or right, where the placement formulas live. It checks row
1 against the roster and aborts on a mismatch rather than writing misaligned
columns into a live site. If it refuses, the roster or the tab is wrong -- do
not work around it.

```bash
python3 cli.py cms                    # what would be written
python3 cli.py cms --csv              # write to exports/cms/ to inspect
python3 cli.py cms --live             # push to the Sheet Framer reads
```

The CMS rule: **a row published in week N is identical in week N+1.** Standings
come out of the frozen weekly snapshots, not from re-running the engine. If a
CMS row changes for a past week, something is wrong -- investigate rather than
re-pushing.

## The stat pack and the newsletter

`cli.py week` writes `newsletters/week-NN/statpack.md`. That is the input to the
newsletter, and every number in it comes from the model rather than from memory.

```bash
python3 cli.py statpack 7      # print a week's pack
python3 cli.py leverage        # remaining games ranked by how much they swing
python3 cli.py who <name>      # career record, picking personality, lines
python3 cli.py h2h <a> <b>     # head to head across shared seasons
```

Generated prose must not contain em dashes or en dashes -- there is a test that
enforces it. Write `--`.

Hand the stat pack to the `fep-master` skill to actually write the newsletter.

## When ESPN is wrong

Results and weights record where they came from. A manual override is
authoritative and `refresh` will never overwrite it, so correcting a bad pull is
safe and permanent:

```bash
python3 cli.py refresh    # pull from ESPN, preserving every manual override
python3 cli.py board      # current board, no snapshot, nothing written
```

`board` is the safe way to look without recording anything. Prefer it whenever
the question is "what does it say right now".

If a *result* was wrong for a week that has already been snapshotted and
pushed, fixing the fact is right but be deliberate about republishing: the CMS
depends on frozen rows staying frozen. Correct it, re-run that week explicitly,
and check what the CMS diff actually contains before `--live`.

## The bye week

2026's bye is **week 10**. The run handles it -- the board is unchanged, the
stat pack says so, and the chart and picks grid both carry a bye row. A week
with no movement is expected, not a failure.

## When the push fails

The commit is already safe locally; only the transport failed. Retry with:

```bash
"$HOME/FEP Data Center/2026/scripts/fep-push.command"
```

This is a personal repo and the machine's active `gh` account is the work one,
so the push needs the personal token supplied per command. `fep-dev` has the
detail. Never `gh auth switch` to fix it.

## Season setup, once a year

```bash
python3 cli.py init                 # schedule, bye week and division games from ESPN
python3 cli.py picks picks.csv      # all 12 pick sheets at once
```

`picks.csv` is one row per competitor: `Name,PointsGuess,G1,...,G17` with W or
L. Loading validates every sheet and refuses anything malformed, so a mis-pasted
row fails loudly instead of scoring against the wrong games.

**Every competitor needs a full sheet before anything works.** The dashboard
refuses to build until all twelve are in, and the failure message names the
missing command rather than the missing people -- so if a build complains about
picks, check the roster for empty sheets first.
