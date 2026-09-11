# The FEP Chart in Framer

One code component for every newsletter. You set a **week number** and it renders
weeks 0 through that week, nothing after.

## What this replaces

| Before | After |
|---|---|
| A hidden `Weighted - W1..W18` tab per week | Nothing |
| A hidden `Straight - W1..W18` tab per week | Nothing |
| A chart-component variant per week | One component |
| A CMS URL field per week pointing at a tab | One `week` number |

Roughly 38 sheet tabs and 19 component variants, deleted. The MASTER tab stays,
because it still feeds the standings on the site. It just no longer feeds the
chart.

## How immutability works now

Each week is published as its own JSON file: `week-07.json` contains weeks 0
through 7 and physically cannot contain week 8. So an old newsletter can never
start showing future data, which was the entire reason the per-week tabs existed.

It also means each URL's contents never change, so it caches forever and there
is no stale-data window after you publish a new week.

Corrections still work. Republish that week's file and it propagates.

## One-time setup

1. **Publish the data.** `cli.py week` writes `chart-data/<year>/week-NN.json`
   and commits it. Both of these serve `access-control-allow-origin: *` with no
   configuration, so the browser can fetch them. Verified live:

   ```
   https://raw.githubusercontent.com/jleibowitz9/fep/main/chart-data
   https://cdn.jsdelivr.net/gh/jleibowitz9/fep@main/chart-data
   ```

   Note there is no year on the end. The component adds `/<year>/week-NN.json`
   itself, which is what lets one instance serve every season.

   Prefer `raw.githubusercontent.com` during the season: jsDelivr caches a branch
   for up to 12 hours, which can delay a correction.

2. **Add the component.** In Framer, open the Assets panel, click the **+** next
   to Code, choose **New Component**, and paste the contents of `FEPChart.tsx`.

3. **Set the base URL once.** Drop the component on the page, and in the
   properties panel set **Data base URL** to the folder URL from step 1. Leave
   off the trailing slash, the year and the filename; the component appends
   `/<year>/week-NN.json` itself.

   A base URL that already ends in a year still works, so an instance set up
   before **Year** existed does not break. The Year control wins either way.

## Weekly use

Set **Year** and **Week** on that newsletter. That is the whole workflow.

To drive it from the CMS instead of typing them, bind both properties to fields
on the newsletter's collection item. If the newsletter references a `weeks` item
whose slug is `2026-w07`, its `season` and `week` fields are exactly these two
numbers.

## Properties

| Property | What it does |
|---|---|
| **Year** | The season. Each year has its own folder of week files. |
| **Week** | Which week to render through. 0 is the preseason board. |
| **Data base URL** | Set once. The folder holding the year folders. |
| **Title** | On by default, auto-generated. Override with Custom title. |
| **W/L strip** | The green/red result badges under the axis. |
| **Background / Text / Muted / Grid** | Colours, defaulted to the Eagles palette. |

## What changed about the chart itself

- **Hovering shows one competitor**, not all twelve including the eliminated
  ones. It finds the nearest line and reports that person's odds, rank, opponent,
  result, and change since last week.
- **No legend.** On desktop, names sit at the end of their own lines. On mobile
  the chips below double as the legend and as tap-to-isolate. All twelve fit.
- **Eliminated competitors stop riding the zero line.** Their line ends with a
  cross on the week they went out, then recedes. In a late-season chart that
  clears six or seven lines out of the live race.
- **The y-axis rounds up to the next 5% above the highest value that week.** A
  week topping out at 36.6% draws to 40, not 100.
- **The legend is ordered by standing**, then alphabetically.
- **A W/L strip under the axis** ties every move to the game that caused it,
  including the bye.

## Fallback

`fep/chart.py` also renders each week as a standalone HTML file with the data
baked in. Useful for dropping a chart into the group chat, and as a backup if
the component is ever inconvenient. Same design, no dependencies, no network.

---

# The FEP Decision Tree in Framer

`FEPDecisionTree.tsx`. One horizontal stacked bar: of every way the rest of the
season can still go, how much is settled on correct picks and how much falls
through to each tiebreaker.

## Why the numbers are properties

Framer's CMS binding reaches text, images, links and visibility. It does **not**
reach a layer's width, which is the one thing a stacked bar needs. A code
component's *properties* can be bound to CMS fields, so the five shares live
there instead of as layers. Bind them and the bar sizes itself from the sheet.

## Setup

1. **Assets > Code > New Component**, name it `FEPDecisionTree`, paste the file.
   It is a default export with a `Props` type and defaults in the signature,
   the same shape as `FEPChart`, so Framer picks it up as a component and every
   property has a value even before you touch the panel.
2. Drop it on the newsletter page.
3. Set **Source** to `Auto (JSON)` and give it the same `baseUrl` as the
   chart. It reads `deciding` out of `{baseUrl}/{year}/week-NN.json`, which the
   weekly run has published for every week since 2026-09-10 -- all of 2025's
   files were republished with it too. Same immutable file the chart reads, no
   CMS column, no sync.

   `Manual / CMS` also works: since 2026-09-11 the `weeks` table carries all
   five shares (`decided_outright`, `decided_tb1`, `decided_tb2`,
   `decided_tb3`, `decided_split`) and their week-over-week changes, so the
   five properties can be bound to fields. Either source gives the same
   numbers; JSON needs no sync.

## The segments

Five, and the component draws four or five depending on the week:

| Key | Default label |
|---|---|
| `outright` | Correct Picks |
| `tb1` | Tiebreaker 1 - Season Record |
| `tb2` | Tiebreaker 2 - Division Record |
| `tb3` | Tiebreaker 3 - Points Total |
| `split` | Fully tied (even split) |

`split` is almost always zero and is hidden when it is. It breaks the colour
ramp on purpose, hatched rather than faded, because it is not the next rung of
the cascade: it is the cascade running out.

## The text inside the bar

Each segment carries its own name and number. Three tiers, so a segment degrades
instead of truncating:

| Segment width | What it shows |
|---|---|
| 30% and up | full name over the number |
| 16% to 30% | short name (`TB2`) over the number |
| 6% to 16% | the number alone |
| under 6% | nothing, the legend has it |

All three thresholds are properties. `Always short` forces the short names
everywhere, and `Text layout` switches the name and number from stacked to side
by side.

**Label ink is worked out per segment, not per bar.** The ramp means the same
colour is near-solid at the top of the cascade and nearly the card at the
bottom, so one ink cannot serve both. Auto blends each fill over `Behind bar` at
that segment's opacity and picks by luminance. That is what lets a dark palette
and a bright one both work without touching the control.

## The reveal

Each segment grows from zero to its width, one after another, so the bar fills
left to right and every layer gets a beat of its own. The text inside a segment
fades in once that segment has mostly landed, and the legend rows follow on the
same stagger.

| Property | |
|---|---|
| `Reveal` | when scrolled into view (default), on page load, or off |
| `Fires at` | how much of the bar has to be on screen, 0 to 1 |
| `Replay` | run it again every time it comes back into view |
| `Duration` | how long one segment takes to grow |
| `Stagger` | gap between one segment starting and the next. 0 grows them together |
| `Easing` | ease out, ease in out, overshoot, linear |

`Fires at` is paired with a bottom margin of 15%, so a bar taller than the
viewport cannot sit there waiting for a threshold it can never cross.

Three cases skip the animation and render the finished state: the Framer canvas
(so you can style it), a reader who has asked for reduced motion, and `Reveal:
off`.

## Two details that matter

**Shares are normalised before drawing.** CMS rounding that sums to 99.9 or
100.1 cannot produce a short or overflowing bar.

**Small segments get a floor.** In 2025 Week 10, TB3 was 2.7%, which is 8px on a
phone. `Min segment` (4% by default) raises it and takes the difference off the
widest segments, so the bar still sums to exactly 100. The floor changes only
the drawn width. The legend always reports the true share.

## Mobile

The bar survives at every width because it is the signature of the segment. The
text comes out of it instead: below 520px the segments go quiet and the legend
carries the labelling, and deltas drop below 360px. Container queries, so it
responds to the frame rather than the device. Note the query measures the
*content* box, so a card with 18px padding hits the 520px breakpoint at about
556px of card.

**The legend is always in the DOM.** Turning it off hides it on wide frames
only. A narrow frame with no inline text and no legend would be a bar with no
labels at all.

## Two things that are easy to break

**The layout annotations live above the function, not in the file header.**
Framer reads `@framerSupportedLayoutWidth` and friends from the comment directly
preceding the exported component. In the header they are just a comment, and the
component silently loses auto height.

**Every default is written twice**, once in the signature and once as a
`defaultValue` in `addPropertyControls`, because Framer needs a literal there and
cannot read the signature. Two copies is two chances to drift, so the preview
build compares all 60 of them and refuses to build when they disagree.

## The preview

```bash
node framer/build-decisiontree-preview.js
```

Regenerates `decisiontree-preview.html` from the component's own CSS, its own
geometry and its own contrast rule, so what you look at is what ships. Same
arrangement as `scrollbar-preview.html`. It runs the defaults check on the way
through.
