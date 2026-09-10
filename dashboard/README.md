# The dashboard

The same page in two modes, decided by one fact: whether anything is behind it.

**Served** (`scripts/FEP.app`, or `python3 dashboard/serve.py`) it is the
application. Tapping the icon starts the server and opens the page: no Terminal
window, and no model run until a button asks for one. About a second, cold.

The launcher starts the server detached and then exits, which is deliberate.
macOS treats a bundle as running for as long as its executable lives, and a tap
on a running app only activates it: the executable never runs again. The first
version stayed alive to own the server, so closing the window left an app that
was still "running" and could not be reopened by tapping it. Exiting instead
means every tap does the same thing, and `serve.py` covers both cases by
opening the window and stopping when a server is already answering. Quit from
the page, which shuts the server down properly.

The bundle is ad-hoc signed (`codesign --force --deep --sign -`). An unsigned
one is assessed on every launch and that alone was over a second. Re-sign it
after editing anything inside it.

`scripts/fep-app.command` is the same thing with a window, for when you want to
watch it start. `serve.py` renders the page from the season file on every load and
exposes the `cli.py` commands as routes, so the buttons run the weekly run, the
ESPN refresh, the Sheet push, the CMS tables, the pick-sheet load and the git
commit. Nothing is reimplemented there: each action is a call into `cli.py`
with its output captured and handed back to the page, so a button and the
command it replaces cannot drift apart.

The page is handed to Chrome with `--app`, which gives a plain window: no tab
strip, no address bar, and none of the localhost developer chrome a browser
adds around a `127.0.0.1` page. Without it the dashboard opened inside Arc's
localhost toolbar and read as a browser looking at a page rather than as an
app. A machine without Chrome falls back to the default browser, and
`FEP_BROWSER=default` turns the preference off.

**Opened as a file** it is a viewer, exactly as it always was. A `file://` page
has no origin, so it cannot reach the season file or start a process, and every
button falls back to copying the command that would. This is the copy that
still works with nothing running, which is why `cli.py dashboard` still writes
it after every run.

```bash
python3 dashboard/serve.py            # the app
python3 cli.py dashboard              # the offline copy, from the live season
python3 dashboard/build.py --mock dashboard/sample-data.json
python3 dashboard/make_fixture.py     # regenerate that mock
node tests/smoke_dashboard.js dashboard/index.html   # does the page survive load
python3 tests/test_serve.py           # the server and its boundary
```

`render()` is the shared step: `build()` writes what it returns to disk, and
`serve.py` writes it straight to the response. The `__LIVE__` placeholder is
how a page learns it has a server; built to a file it is replaced with nothing
and the front end stays in its copy-the-command mode.

## Why it opens instantly

`collect()` costs about eleven seconds, almost all of it precomputing a
counterfactual board for every remaining game twice over: once for What If and
once for the leverage ranking. Doing that on every page load made tapping the
icon feel like running the model, which is exactly what it is not supposed to
do.

So the payload is cached in `data/dashboard_cache/` (gitignored) against a
fingerprint of everything it is a function of: the season file, `build.py`,
every module in `fep/`, and `data/history/`. Touch any of them and the next
load recomputes. That is the whole safety argument -- editing `fep/analytics.py`
and being served yesterday's numbers would be a far worse bug than the wait it
saves, so the key has to cover the code and not just the data.

Two more things follow from a cache being a file on disk that nothing validates
on the way in. `REQUIRED_KEYS` rejects a cached payload that is truncated,
written by an older `collect()`, or otherwise not a payload, so a bad file
means one slow load rather than a dead server; and `_page()` reports what went
wrong instead of dropping the connection, because an empty reply reads as "the
app never started". Both exist because a test once wrote a stub object into the
real cache and took the server down with it.

The weekly run rebuilds the cache as one of its own steps, so the reload after
a run is instant too, and the offline `index.html` is built from that same
payload rather than a second identical computation.

Two things guard the server, because it is the only surface here that takes
input from outside the process and one of its actions writes to a real Google
Sheet. It binds `127.0.0.1` only, and every action requires a token minted at
launch and handed to the page it rendered, so another site in the same browser
cannot reach it. Writes that leave this machine arm on the first press and fire
on the second.

| File | What it is |
|---|---|
| `template.html` | the entire front end: markup, CSS and JS, hand written |
| `serve.py` | the app: renders the page live and runs `cli.py` behind the buttons |
| `build.py` | `collect()` defines the exact shape of `__DATA__`, `render()` the page |
| `sample-data.json` | **generated**, and synthetic. A full week 7 payload for working on the front end out of season. The results are invented, drawn from the real ESPN win probabilities with a fixed seed |
| `make_fixture.py` | builds `sample-data.json` *through* `collect()`, so the fixture can never carry a key the live builder does not produce |
| `index.html` | **generated**. Never edit it; edit `template.html` and rebuild |
| `assets/fep-logo.png` | referenced by relative path, so open `index.html` from this folder |

The chart inside the Chart tab is rendered by `../fep/chart.py`, not by the
template. The Framer version of the same chart is `../framer/FEPChart.tsx`.

## The payload contract

`collect()` is the only definition of `__DATA__`. Two rules keep it honest:

- `analytics.pin(season, week)` decides what "as of week N" means -- it masks
  later games *and* drops later snapshots. Anything derived from snapshots
  (sparklines, Heat Check, volatility) goes through it, so a historical build
  cannot show a past board beside future numbers.
- `sample-data.json` is generated by running `collect()` over a seeded
  synthetic season, not hand-assembled. `tests/test_review_fixes.py` asserts
  the fixture and the live payload have the same keys. The What If tab was
  broken in exactly this gap: the mock had a `whatif` key that `collect()`
  never produced, so the tab worked in development and reported "No
  precomputed board" against every live build.
