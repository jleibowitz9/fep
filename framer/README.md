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

1. **Publish the data.** Commit the `chart-data/` folder to a public GitHub repo
   (the existing `eagles-simulator` repo is fine). Both of these serve
   `access-control-allow-origin: *` with no configuration, so the browser can
   fetch them:

   ```
   https://raw.githubusercontent.com/jleibowitz9/eagles-simulator/main/chart-data/2026
   https://cdn.jsdelivr.net/gh/jleibowitz9/eagles-simulator@main/chart-data/2026
   ```

   Prefer `raw.githubusercontent.com` during the season: jsDelivr caches a branch
   for up to 12 hours, which can delay a correction.

2. **Add the component.** In Framer, open the Assets panel, click the **+** next
   to Code, choose **New Component**, and paste the contents of `FEPChart.tsx`.

3. **Set the base URL once.** Drop the component on the page, and in the
   properties panel set **Data base URL** to the folder URL from step 1. Leave
   off the trailing slash and the filename; the component appends
   `/week-NN.json` itself.

## Weekly use

Set **Week** on that newsletter. That is the whole workflow.

To drive it from the CMS instead of typing it, bind the `Week` property to a
number field on the newsletter's collection item.

## Properties

| Property | What it does |
|---|---|
| **Week** | Which week to render through. 0 is the preseason board. |
| **Data base URL** | Set once. The folder holding `week-NN.json`. |
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
