# FEP Algorithm Review, 2026

An adversarial, staff-engineer and staff-PM review of the FEP simulator as it
stood at the end of the 2025 season, plus what changed.

Everything below was verified by reading and running the code. Where a finding
turned out to be wrong under testing, that is recorded rather than quietly
dropped, because two of them did.

---

## Summary

The core math was **sound**. The tiebreaker cascade was correct in order and in
mechanics, universes were weighted correctly, boards normalised to 100%, and
the mid-season points projection was maintained correctly for all of 2025. The
new engine reproduces all 216 published 2025 board cells exactly.

The problems were around the edges: one latent correctness bug, no validation,
no persistence, a doubled inner loop, and a weekly process that depended on
hand-typing about twenty numbers into a source file.

---

## Correctness

### F1. Identical points guesses split unevenly. Real, latent, now fixed.

`closest_shares_normal` sorted competitors by points guess and gave each the
Normal probability mass between the midpoints to its neighbours. Two competitors
who submitted the **same** number put the midpoint exactly on that number, so
one took all the mass below it and the other all the mass above.

Demonstrated: two identical 400-point guesses split **63.1 / 36.9** instead of
50/50, and the gap widens the further the projected total sits from the shared
guess.

**I initially reported that this corrupted every published 2025 board. That was
wrong, and testing caught it.** Emer and Jen were the only pair sharing a guess
(both 455). They also share a predicted record (13-4), so tiebreaker 1 cannot
separate them, but their division records differ (5-1 against 6-0). Since
`|5 - a|` can never equal `|6 - a|` for an integer `a`, **tiebreaker 2 separates
them in every possible universe**. The points tiebreaker was never reached for
that pair, and 2025 is unaffected.

So it is a landmine, not a wound. It fires the first time two competitors tie on
correct picks *and* record *and* division record while sharing a points guess.
Given the pool has twelve people picking round numbers, that is a matter of time.

Fixed by grouping equal guesses, computing the group's interval once, and
splitting it evenly. Locked in by `test_tied_points_guesses_split_evenly` and
`test_tiebreaker_2_only_runs_after_tiebreaker_1`.

### F2. No terminal fallback when the cascade is exhausted. Fixed.

If two competitors tied on picks, record, division record *and* points guess,
nothing was left to separate them and the old code only produced a sane answer
by accident of normalisation. Now an explicit even split, reported as its own
`split` layer so the newsletter can say it happened.

### F3. No input validation at all. Fixed.

Nothing checked that a pick sheet was 17 long, that `division_weeks` indices
were in range, or that weights were in [0, 1]. A mis-pasted row either threw
somewhere deep in the loop or silently scored against the wrong games. Now
validated on load with a specific error message, covered by seven tests.

---

## Efficiency

### F4. Every board was computed twice. Fixed.

`run_simulation` called `simulate(True)` then `simulate(False)`, and each call
rebuilt the **identical** 12-competitor tally before allocating to the weighted
or the straight board. Exactly 2x waste, for nothing.

### F5. The hot loop compared strings. Fixed.

Measured on a preseason board (2^17 = 131,072 universes):

| | Old | New |
|---|---|---|
| One board | 3.54s | **0.29s** (12.1x) |
| Rank all 17 games by leverage | ~120s | **4.7s** |

Picks are now bitmasks and scoring is a popcount, so the inner loop is integer
work. A single board was always tolerable; the leverage sweep at two minutes was
not, and that is precisely why the deeper analytics had never been built.

---

## Robustness and process

### F6. Importing the module ran a simulation and printed to stdout. Fixed.

`2025/simulator.py` executed both full passes at module scope, and `app.py`
imported it. Now nothing runs on import.

### F7. `actual_points` was a hand-retyped arithmetic literal. Fixed by removing the need for it.

Line 51 read `(24+20+33+...) / N * 17`, retyped every week. **Checked against
every weekly commit in the 2025 repo: it was maintained correctly all season, so
this was never a live bug.** It was simply the most dangerous line in the file,
because a typo would silently reshuffle every tiebreaker with no visible symptom.
ESPN supplies the scores, so it is now derived.

### F8. The points projection was fragile in the weeks it mattered most. Improved, with the old behaviour preserved.

The mean was a pure pace projection. After Week 1 of 2025 that meant a single
24-point game projecting the season at 408, and the spread modelled only the
remaining games while treating that pace as if it were known exactly.

The default is now shrunk toward a prior and the spread carries the uncertainty
in the rate itself. `points_model="legacy"` reproduces 2025 exactly, and
`legacy` is provably the same as `shrunk` with `prior_weight_games = 0`, which
is a useful way to see what the change actually does.

### F9. The dashboard did not remove the code-editing step.

`2025/app.py:47` locked any week whose result was baked into the imported
module, so the deployed app could neither change a result nor explore a
counterfactual on a past game. Results were still only editable in source. This
is why the app never actually saved any time. Superseded.

### F10. Three plausible "the algorithm" files, two of them a year stale.

`2025/FEP Algorithm with Tiebreakers.py` and its `copy` both contain the **2024**
picks (verified byte-identical to `2024/FEP 2024.py`, and different from
`2025/simulator.py`).

The canonical finished 2025 file is **`2025/simulator.py`**: zero unplayed games,
Eagles 11-6, 379 points, Pop 11 correct and Marsha second at 10, matching the
record book. It is also byte-identical to the copy in the fep-master skill.

### F11. Nothing persisted. Fixed.

No weekly snapshot existed, so Heat Check deltas, season-arc charts and
biggest-rise superlatives had to be reconstructed by hand or dug out of git.
Snapshots are now part of the season file, **including the weights that produced
them** (see the note on validation limits below).

### F12. Played games had to be a contiguous prefix. Fixed.

The old loop assumed everything before `week_number` was played. That made
retrospective analysis impossible, because forcing a *past* game the other way
produces a non-contiguous result set. Any subset can now be unplayed, which is
what powers retrospective leverage and the counterfactual.

### F13. Late newsletters could contaminate a snapshot. Found during end-to-end testing, fixed.

`cli.py week 12` refreshes from ESPN, and ESPN may already carry a Thursday
result from Week 13. Without care, the Week 12 snapshot would silently include a
game that had not happened when that week's board was published. Boards are now
pinned with `through_week`, so a week's snapshot reflects only what was known
then. Verified: a Week 10 run on the completed 2025 season correctly reports 256
remaining outcomes, ignoring the eight later results ESPN already has.

---

## Two bugs the Framer chart component only revealed when actually rendered

Both were invisible on inspection and would have surfaced in Framer.

1. **The ResizeObserver never attached.** The component returns a placeholder
   while data loads, so a `useEffect` with `[]` dependencies ran once against a
   null ref and never observed anything. Width stayed at its 760 default, so the
   chart rendered desktop-width layout inside a 470px box. Fixed with a callback
   ref.
2. **The tooltip derived its position from the viewBox** and ignored the header
   above the SVG, placing it off the right edge. Fixed by measuring the real
   element boxes, with edge flipping.

The React harness that caught these is worth keeping.

---

## What could not be validated, and why it matters

The leverage implementation reproduces the *shape* and *ranking* of the numbers
Jacob published in 2025, but not the decimals. The Week 10 Packers preview
computes **67.6%** where the newsletter said **63%**.

The cause is not the code. `2025/simulator.py` preserves only the **final** set
of weights, and the weights for unplayed games moved substantially during the
season (game 14 went from .475 to .632, game 16 from .543 to .702). The Week 10
weights no longer exist, so that board cannot be reconstructed.

This is the single strongest argument for the new snapshot format, which stores
the weights alongside every board. From 2026 on, any past week can be
reproduced exactly.

The same caveat applies to replaying 2025 through the new pipeline end to end:
ESPN now returns each game's final pre-kickoff projection, not the preseason
number Jacob used in Week 0, so a replayed Week 0 board will not match the
published one. **When given the same weights, the engine matches exactly**, and
that is what the regression test asserts.

---

## Staff PM view: what the algorithm can now tell you that it could not before

Previously the model produced one number per competitor per week. Everything
else in the newsletter was assembled by hand or by asking a chatbot. All of the
following now come out of a single call, in under a second, and are in the
weekly stat pack.

**Already-franchised segments, now computed rather than assembled**
- Heat Check, from real snapshots rather than memory
- Leverage Index for the next game, and every remaining game ranked
- The Counterfactual, as a full alternate board
- **The Decision Tree**, which had no implementation anywhere. The share of
  remaining outcomes settled outright versus by each tiebreaker layer, with a
  week-over-week delta.
- Elimination watch, including who goes out on the next win and on the next loss

**New**
- **Differentiation.** Average distance of each remaining pick sheet from the
  field, plus who your nearest rival is. This quantifies the thing that actually
  kills FEP campaigns: being correct in exactly the same way as someone who
  beats you on tiebreakers. In the Week 10 2025 board it immediately surfaces
  that Hanan, Jay and Sarah had *identical* remaining sheets.
- **Expected final correct picks.** A cleaner read on who is picking well than
  win probability, which is distorted by tiebreaker position.
- **Floor and ceiling** per competitor.
- **Retrospective leverage.** Which single past game cost each competitor the
  most equity. This is the regret engine.
- **Chalk index.** Where the field agrees and where it splits, which is exactly
  the "circle these games" preview callout, plus how the field's consensus
  compares to ESPN's line.
- **Volatility.** Total movement, peak and peak week per competitor. Feeds
  Biggest Rise, Biggest Fall and the Main Character Energy award.
- **Field concentration.** How open the race is as one number, tracked weekly.
- **ESPN calibration.** A Brier score against actual results. In 2025 through
  nine games ESPN scored 0.2622, which is *worse than a coin flip*, and had
  projected 5.21 wins against an actual 7. That is a recurring meta-stat with a
  built-in joke.

**A worked example of the model finding a story on its own.** Replaying 2025,
the Week 12 and Week 13 boards come out identical to the decimal. That looked
like a bug. It is not: every competitor still alive had picked the Bears game
the same way, so the loss cost all of them one point and redistributed nothing.
The chalk index flags that game at consensus 1.00. A genuine non-event, and a
newsletter line the old setup had no way to notice.

---

## Deliberately left alone

- **Games are treated as independent.** Not strictly true, but it is the
  agreed-upon convention, it keeps the math legible, and changing it would break
  comparability with ten years of history.
- **Points are modelled independently of which games are won.** Same reasoning.
  Winning teams score more, but coupling them would complicate the tiebreaker
  for a second-order effect.
- **The tiebreaker order.** It is the family's rule, not an implementation
  detail.
