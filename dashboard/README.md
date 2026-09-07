# The dashboard

One HTML file. `build.py` reads `template.html`, substitutes the week's data
into the `__DATA__` placeholder and the chart renderer into `__CHART__`, and
writes `index.html`. That file opens with a double click, works offline, and
shows exactly the week it was built for.

```bash
python3 cli.py dashboard              # the live season
python3 dashboard/build.py --mock dashboard/sample-data.json
```

| File | What it is |
|---|---|
| `template.html` | the entire front end: markup, CSS and JS, hand written |
| `build.py` | `collect()` defines the exact shape of `__DATA__` |
| `sample-data.json` | a full week 7 payload, for working on the front end without a live season |
| `index.html` | **generated**. Never edit it; edit `template.html` and rebuild |
| `assets/fep-logo.png` | referenced by relative path, so open `index.html` from this folder |

The chart inside the Chart tab is rendered by `../fep/chart.py`, not by the
template. The Framer version of the same chart is `../framer/FEPChart.tsx`.
