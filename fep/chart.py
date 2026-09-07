"""
The FEP chart.

Generates a self-contained, immutable chart for one week of the season.

WHY THIS EXISTS
---------------
The old setup bought immutability the expensive way: a hidden "Weighted - W7"
tab per week filtering the MASTER sheet, a CMS field per week holding that
tab's URL, and a chart-component variant per week, all so that the Week 7
newsletter keeps showing Week 7 data forever. That is roughly 38 sheet tabs and
19 component variants per season, maintained by hand.

Baking the data into the chart at publish time gets the same immutability for
free. Week 7's chart contains weeks 0..7 and cannot change, because there is
nothing external for it to read. No API, no tabs, no variants.

WHAT IT FIXES ABOUT THE OLD CHART
---------------------------------
* Hover showed all twelve competitors at once, including the six sitting at
  zero. Now it finds the nearest line and shows only that person, with their
  rank and their change since last week.
* The legend was unusable on mobile (five names, truncated). Gone entirely,
  replaced by labels at the end of each line, which is also fewer eye movements
  on desktop.
* Six eliminated competitors rode the zero line forever as an uninformative
  black band. Now a line ends with a marker on the week its owner was
  eliminated, and they move to a roster strip underneath. The elimination week
  is a story, so it is shown rather than flattened.
* The y-axis was always 0..100 even when nothing exceeded 35, so ten weeks of
  real movement were squashed into the bottom third. It now fits the data on
  screen.
* Games were invisible. A W/L strip under the axis ties every move to the
  result that caused it.

Output is one HTML file with inline SVG and a small amount of vanilla
JavaScript. No libraries, no network. It renders as a static chart with
JavaScript disabled; JavaScript only adds interaction.
"""

from __future__ import annotations

import html
import colorsys
import json
from typing import Dict, List, Optional, Sequence

# The FEP competitor colours. These are canonical: they are the colours used on
# the Framer site, and they identify a *person*, not a position in a list.
#
# Keyed by name deliberately. They used to be a list indexed by roster position,
# which meant a thirteenth competitor whose name sorted early (say "Dave")
# shifted the colour of everyone after them and silently handed the thirteenth
# person the first person's exact colour via the modulo. Nine of twelve
# identities changed because one person joined.
CANONICAL = {
    "Amir": "#972B2B", "Andy": "#97612B", "Buhduh": "#97972B",
    "Emer": "#61972B", "Hanan": "#2B972B", "Jacob": "#2B9761",
    "Jay": "#2B9797", "Jen": "#2B6197", "Marsha": "#2B2B97",
    "Nathan": "#612B97", "Pop": "#972B97", "Sarah": "#972B61",
}

# Those twelve are not an arbitrary list, they are a rule: twelve hues thirty
# degrees apart, every one at exactly this lightness and saturation. Verified by
# regenerating all twelve hexes from the rule and comparing.
#
# Which is what makes the palette safe to grow. A thirteenth competitor takes a
# hue halfway between two existing ones, so nobody's colour ever moves and no
# two people are ever closer than fifteen degrees apart.
PALETTE_LIGHTNESS = 0.38
PALETTE_SATURATION = 0.56

# Roster order, so old callers and the published 2025 charts are unaffected.
PALETTE = [CANONICAL[n] for n in (
    "Amir", "Andy", "Buhduh", "Emer", "Hanan", "Jacob",
    "Jay", "Jen", "Marsha", "Nathan", "Pop", "Sarah")]


def _hue_to_hex(hue: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(
        (hue % 360.0) / 360.0, PALETTE_LIGHTNESS, PALETTE_SATURATION)
    return "#{:02X}{:02X}{:02X}".format(
        *(int(round(channel * 255)) for channel in (red, green, blue)))


def _hue_sequence():
    """Hues in the order the palette hands them out: the wheel, then its gaps.

    30 degrees apart for the first twelve, then the midpoints of those, then the
    midpoints of those. Each pass stays as far from every earlier hue as that
    pass allows, so the palette degrades gracefully instead of collapsing.
    """
    step = 30.0
    for k in range(12):
        yield k * step
    while step > 1.0:
        offset = step / 2.0
        for k in range(int(round(360.0 / step))):
            yield offset + k * step
        step /= 2.0


def colors_for(roster, assigned=None) -> Dict[str, str]:
    """A colour per competitor, stable for life.

    Precedence: a colour already recorded for that person, then the canonical
    twelve, then the next unused hue. Recording the result (season.py does this)
    is what makes a newcomer's colour permanent rather than a function of who
    else happens to be on the roster.
    """
    colors = dict(assigned or {})
    for name in roster:
        if name not in colors and name in CANONICAL:
            colors[name] = CANONICAL[name]

    unclaimed = [name for name in roster if name not in colors]
    if unclaimed:
        taken = {value.upper() for value in colors.values()}
        hues = _hue_sequence()
        for name in unclaimed:
            for hue in hues:
                candidate = _hue_to_hex(hue)
                if candidate.upper() not in taken:
                    colors[name] = candidate
                    taken.add(candidate.upper())
                    break
            else:  # pragma: no cover - the sequence is effectively unbounded
                raise ValueError("ran out of distinct colours for {}".format(name))
    return colors

# The canonical colours are mid-dark by design, which is right for a filled pill
# but not for a 3px line on a near-black chart: measured against the chart
# ground, only seven of the twelve clear a 3.0 contrast ratio, and Marsha's
# #2B2B97 sits at 1.75, effectively invisible. Raising lightness in HLS (rather
# than blending toward white) keeps the hue and the saturation exactly and lifts
# every competitor above 4.1. So: canonical colour for fills, this for strokes.
LINE_LIGHTNESS = 0.62


def _relight(hex_color: str, lightness: float) -> str:
    import colorsys
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, _, sat = colorsys.rgb_to_hls(r, g, b)
    return "#%02X%02X%02X" % tuple(
        round(c * 255) for c in colorsys.hls_to_rgb(hue, lightness, sat))


def _luminance(hex_color: str) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


DARK_INK = "#0C0E10"


def _ink_on(hex_color: str) -> str:
    """Whichever of near-black or white actually reads on this swatch.

    Measure both rather than thresholding on luminance: the yellow-greens sit
    right on the boundary, and a threshold picked by eye gets them wrong.
    """
    return (DARK_INK if _contrast(DARK_INK, hex_color) >= _contrast("#FFFFFF", hex_color)
            else "#FFFFFF")


DIM = "#4a5568"


def week_label(week: int, bye_week: Optional[int] = None) -> str:
    if week == 0:
        return "P"
    return "W{}".format(week)


def build_series(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    colors: Optional[Dict[str, str]] = None,
    eliminated: Optional[Dict[int, Sequence[str]]] = None,
) -> List[dict]:
    """Turn {week: {name: pct}} into per-competitor series with elimination info.

    A competitor is "eliminated" at the first week their odds hit zero and never
    recover. Trailing zeros are trimmed off the drawn line so it terminates at
    the elimination point instead of crawling along the axis.

    `eliminated` is {week: [names mathematically out]}, taken from the snapshots
    where the board is still unrounded. Without it this reads elimination off
    the displayed percentage, and a competitor clinging on at 0.04% displays as
    0.0 and is indistinguishable from one who is finished. Optional, because the
    already-published files were built without it and must not change.
    """
    colors = colors_for(roster, colors)
    series = []
    for name in roster:
        color = colors[name]
        values = [board_by_week.get(w, {}).get(name) for w in weeks]
        values = [None if v is None else float(v) for v in values]

        # Find the last week this competitor was still alive.
        last_alive = None
        for i, value in enumerate(values):
            if value is None:
                continue
            if eliminated is not None and weeks[i] in eliminated:
                alive = name not in eliminated[weeks[i]]
            else:
                alive = value > 0
            if alive:
                last_alive = i

        if last_alive is None:
            eliminated_at = weeks[0]
            drawn = values[:1]
        elif last_alive < len(values) - 1:
            # Keep one zero point so the line visibly lands on the axis.
            eliminated_at = weeks[last_alive + 1]
            drawn = values[: last_alive + 2]
        else:
            eliminated_at = None
            drawn = values

        series.append(
            {
                "name": name,
                "color": color,
                "line": _relight(color, LINE_LIGHTNESS),
                "ink": _ink_on(color),
                "values": values,
                "drawn": drawn,
                "eliminated_at": eliminated_at,
                "current": values[-1] if values else None,
                "peak": max([v for v in values if v is not None] or [0.0]),
            }
        )
    return series


def _ranks(series: List[dict], index: int) -> Dict[str, int]:
    """Standings at a week. Eliminated competitors all share last place."""
    live = [(s["name"], s["values"][index] or 0.0) for s in series]
    live.sort(key=lambda pair: (-pair[1], pair[0]))
    ranks, previous_value, previous_rank = {}, None, 0
    for position, (name, value) in enumerate(live, start=1):
        if value == previous_value:
            ranks[name] = previous_rank
        else:
            ranks[name] = position
            previous_rank, previous_value = position, value
    return ranks


def build_payload(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]] = None,
    year: int = 2026,
    upto_week: Optional[int] = None,
    colors: Optional[Dict[str, str]] = None,
    eliminated: Optional[Dict[int, Sequence[str]]] = None,
) -> dict:
    """The data a chart needs for one week, and nothing after it.

    This is what gets written to chart-data/<year>/week-NN.json and fetched by
    the Framer component. Truncating here rather than in the renderer is what
    makes each published file immutable: the Week 7 file cannot show Week 8
    because it does not contain Week 8.
    """
    if upto_week is not None:
        weeks = [w for w in weeks if w <= upto_week]
    weeks = list(weeks)
    if not weeks:
        raise ValueError("no weeks to chart")

    series = build_series(weeks, board_by_week, roster, colors, eliminated)
    games = games or {}

    return {
        "year": year,
        "week": weeks[-1],
        "weeks": weeks,
        "labels": [week_label(w) for w in weeks],
        "series": [
            {
                "name": s["name"],
                "color": s["color"],
                "line": s["line"],
                "ink": s["ink"],
                "values": s["values"],
                "drawn": s["drawn"],
                "eliminatedAt": s["eliminated_at"],
                "current": s["current"],
                "peak": s["peak"],
            }
            for s in series
        ],
        "games": [
            {
                "week": w,
                "label": (games.get(w) or {}).get("label"),
                "result": (games.get(w) or {}).get("result"),
            }
            for w in weeks
        ],
        "ranks": [_ranks(series, i) for i in range(len(weeks))],
        "dim": DIM,
    }


def render(
    weeks: Sequence[int],
    board_by_week: Dict[int, Dict[str, float]],
    roster: Sequence[str],
    games: Optional[Dict[int, dict]] = None,
    year: int = 2026,
    upto_week: Optional[int] = None,
    title: Optional[str] = None,
    standalone: bool = True,
    colors: Optional[Dict[str, str]] = None,
    eliminated: Optional[Dict[int, Sequence[str]]] = None,
) -> str:
    """Render one week as a self-contained HTML file.

    Used for the stat pack, for sending a chart into the group chat, and as the
    fallback if the Framer component is ever inconvenient. The Framer path uses
    build_payload directly.
    """
    payload = build_payload(weeks, board_by_week, roster, games, year,
                            upto_week, colors, eliminated)
    heading = title or "{} Family Eagles Pool | {}".format(
        payload["year"], week_label(payload["weeks"][-1])
    )
    body = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)).replace(
        "__TITLE__", html.escape(heading)
    )
    if not standalone:
        return body
    return _PAGE.replace("__TITLE__", html.escape(heading)).replace("__BODY__", body)


def render_from_season(season: dict, upto_week: Optional[int] = None, **kwargs) -> str:
    """Convenience wrapper that reads snapshots straight out of a season file."""
    snapshots = {s["week"]: s["weighted"] for s in season.get("snapshots", [])}
    if not snapshots:
        raise ValueError("season has no snapshots yet; run and save a week first")

    games = {}
    for game in season["games"]:
        games[game["nfl_week"]] = {"label": game["label"], "result": game["result"]}
    for bye in (season.get("bye_weeks")
                or ([season["bye_week"]] if season.get("bye_week") else [])):
        games[bye] = {"label": "Bye", "result": None}

    return render(
        weeks=sorted(snapshots),
        board_by_week=snapshots,
        roster=season["roster"],
        games=games,
        year=season["year"],
        upto_week=upto_week,
        colors=season.get("colors"),
        eliminated={s["week"]: s["eliminated"]
                    for s in season.get("snapshots", [])
                    if s.get("eliminated") is not None} or None,
        **kwargs
    )


# ---------------------------------------------------------------------------
# the markup
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title></head><body style="margin:0">__BODY__</body></html>"""


_TEMPLATE = r"""
<div class="fep-chart" data-fep>
<style>
.fep-chart{--bg:#06231f;--bg2:#04302a;--ink:#eafaf6;--muted:#7f9c96;--grid:#12463f;
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:linear-gradient(160deg,var(--bg2),var(--bg));color:var(--ink);
  border-radius:14px;padding:18px 16px 14px;position:relative;container-type:inline-size}
.fep-chart *{box-sizing:border-box}
.fep-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:20px}
.fep-title{font-size:19px;font-weight:800;font-style:italic;letter-spacing:.2px;margin:0}
.fep-svg{display:block;width:100%;height:auto;touch-action:pan-y;overflow:visible}
.fep-line{fill:none;stroke-width:3;stroke-linejoin:round;stroke-linecap:round;
  transition:opacity .12s}
.fep-dot{transition:opacity .12s}
.fep-axis{font-size:10.5px;fill:var(--muted);font-variant-numeric:tabular-nums}
.fep-grid{stroke:var(--grid);stroke-width:1}
/* Vertical rules are for reading a week off the axis, so they sit well behind
   the horizontal value lines rather than competing with them. */
.fep-vgrid{opacity:.42}
.fep-res{font-size:9.5px;font-weight:800;letter-spacing:.3px}
.fep-dimmed{opacity:.12}
.fep-tip{position:absolute;pointer-events:none;background:#041e1af5;
  border:1px solid #ffffff30;border-radius:10px;padding:9px 11px;font-size:12px;
  box-shadow:0 8px 24px #00000073;
  opacity:0;transition:opacity .1s;min-width:150px;z-index:5}
.fep-tip b{font-size:13.5px;font-weight:800}
.fep-tip .row{display:flex;justify-content:space-between;gap:14px;margin-top:4px;
  color:#a9c4be;font-size:11.5px}
.fep-tip .row span:last-child{color:#ffffff;font-weight:700;font-variant-numeric:tabular-nums}
.fep-tip .game{display:block;margin-top:4px;color:#cfe3df;font-size:11.5px;font-weight:600}
.fep-roster{display:flex;flex-wrap:wrap;gap:5px;margin-top:11px}
.fep-chip{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
  padding:4px 9px;border-radius:999px;background:rgba(255,255,255,.05);cursor:pointer;
  border:1px solid transparent;user-select:none}
.fep-chip[data-out="1"]{color:var(--muted);text-decoration:line-through;opacity:.65}
.fep-chip[aria-pressed="true"]{border-color:currentColor;background:rgba(255,255,255,.12)}
.fep-swatch{width:8px;height:8px;border-radius:2px;flex:none}
@container (max-width:520px){
  .fep-title{font-size:16px}
}
</style>

<div class="fep-head">
  <p class="fep-title">__TITLE__</p>
</div>

<svg class="fep-svg" data-svg role="img" aria-label="Weekly championship odds"></svg>
<div class="fep-tip" data-tip></div>
<div class="fep-roster" data-roster></div>

<script type="application/json" data-payload>__PAYLOAD__</script>
<script>
(function(){
  // document.currentScript is null when a script is injected and executed
  // dynamically (as the dashboard does when it mounts this chart), so fall back
  // to the first chart container that has not been drawn into yet.
  var root = (document.currentScript && document.currentScript.closest('[data-fep]'));
  if (!root) {
    var all = document.querySelectorAll('[data-fep]');
    for (var q = 0; q < all.length; q++) {
      var svg = all[q].querySelector('[data-svg]');
      if (svg && !svg.childNodes.length) { root = all[q]; break; }
    }
    if (!root) root = all[all.length - 1];
  }
  if (!root) return;
  var D = JSON.parse(root.querySelector('[data-payload]').textContent);
  var svg = root.querySelector('[data-svg]');
  var tip = root.querySelector('[data-tip]');
  var NS = 'http://www.w3.org/2000/svg';
  var pinned = null, hover = null;

  var W = 760, H = 420;
  function narrow(){ return root.clientWidth < 520; }
  // A 760x420 viewBox is ~200px tall once scaled onto a phone, which squashes
  // the whole race into a band. Go taller (and relatively narrower) there.
  function sizeFor(){ H = narrow() ? 560 : 420; }

  function el(n, a){ var e = document.createElementNS(NS, n);
    for (var k in a) if (a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]); return e; }

  // Only competitors who ever mattered get a drawn line; the rest are in the
  // roster strip. Sorted so the current leaders are painted last (on top).
  function ordered(){
    return D.series.slice().sort(function(a,b){ return (a.current||0) - (b.current||0); });
  }

  function scales(){
    var left = narrow() ? 30 : 36;
    var right = 14;   // no end labels any more, so the plot gets the width
    var top = 20, bottom = 54;
    var maxV = 0;
    D.series.forEach(function(s){ s.values.forEach(function(v){ if (v > maxV) maxV = v; }); });
    // Round up to the next 5% and stop. No decorative headroom: a week topping
    // out at 36.6 draws to 40, not 50.
    var ceil = Math.max(5, Math.ceil(maxV / 5) * 5);
    // Pick the largest round step that divides the ceiling EXACTLY and still
    // leaves at least three bands. Exact division matters: with a ceiling of 35
    // and a step of 10 the top gridline lands on 30 and the axis appears to
    // stop short of its own maximum.
    var step = 5;
    [5, 10, 15, 20, 25, 50].forEach(function(c){
      if (ceil % c === 0 && ceil / c >= 3) step = c;
    });
    return {
      left: left, right: right, top: top, bottom: bottom, ceil: ceil, step: step,
      x: function(i){ return left + (W - left - right) * (D.weeks.length === 1 ? .5 : i / (D.weeks.length - 1)); },
      y: function(v){ return top + (H - top - bottom) * (1 - v / ceil); }
    };
  }

  function valueAt(s, i){ return s.values[i]; }

  function draw(){
    sizeFor();
    var S = scales();
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

    var every = narrow() ? (D.weeks.length > 10 ? 3 : 2) : 1;
    var rightEdge = W - S.right + (narrow() ? 8 : 6);

    // vertical gridlines, one per week
    D.labels.forEach(function(lab, i){
      svg.appendChild(el('line', {x1:S.x(i), x2:S.x(i), y1:S.top, y2:H - S.bottom,
        class:'fep-grid fep-vgrid'}));
    });

    // horizontal gridlines + y axis

      for (var v = 0; v <= S.ceil + .001; v += S.step){
        var y = S.y(v);
        svg.appendChild(el('line', {x1:S.left, x2:rightEdge, y1:y, y2:y, class:'fep-grid'}));
        var t = el('text', {x:S.left - 7, y:y + 3.5, class:'fep-axis', 'text-anchor':'end'});
        t.textContent = Math.round(v) + '%';
        svg.appendChild(t);
      }

    // x axis: week labels, thinned on narrow screens
    D.labels.forEach(function(lab, i){
      if (i % every !== 0 && i !== D.labels.length - 1) return;
      var t = el('text', {x:S.x(i), y:H - S.bottom + 16, class:'fep-axis', 'text-anchor':'middle'});
      t.textContent = lab; svg.appendChild(t);
    });

    // result strip: what actually happened that week
    D.games.forEach(function(gm, i){
      if (i % every !== 0 && i !== D.games.length - 1) return;
      if (!gm.result && gm.label !== 'Bye') return;
      var isW = gm.result === 'W', isBye = gm.label === 'Bye';
      var fill = isBye ? '#2c4a45' : (isW ? '#1f7a4d' : '#7a2130');
      var x = S.x(i), y = H - S.bottom + 24;
      svg.appendChild(el('rect', {x:x-9, y:y, width:18, height:14, rx:4, fill:fill}));
      var t = el('text', {x:x, y:y+10.2, class:'fep-res', 'text-anchor':'middle', fill:'#eafaf6'});
      t.textContent = isBye ? '—' : (gm.result || '');
      svg.appendChild(t);
    });

    var focus = pinned || hover;

    ordered().forEach(function(s){
      var pts = [];
      var upto = s.drawn.length;
      for (var i = 0; i < upto; i++){
        var v = valueAt(s, i);
        if (v === null || v === undefined) continue;
        pts.push([S.x(i), S.y(v)]);
      }
      if (!pts.length) return;

      var out = s.eliminatedAt !== null && s.eliminatedAt !== undefined;
      // Canonical colour identifies the person; the lifted one is what can
      // actually be seen as a line on this ground.
      var color = out ? D.dim : (s.line || s.color);
      var cls = 'fep-line' + (focus && focus !== s.name ? ' fep-dimmed' : '');

      var path = el('path', {
        d: 'M' + pts.map(function(p){ return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L'),
        stroke: color, class: cls, 'data-name': s.name
      });
      // Eliminated campaigns stay as history but recede hard: thin and faint,
      // so the live race is unmistakably the subject. Hovering one brings it
      // back to full weight.
      if (out){
        path.setAttribute('stroke-width', '2.1');
        if (focus !== s.name) path.setAttribute('opacity', '.45');
      }
      svg.appendChild(path);

      var last = pts[pts.length - 1];
      var dimmed = focus && focus !== s.name;

      // A dot at every vertex, so each week is a readable data point rather
      // than an inferred bend in a line.
      // Dots only for competitors still alive (and for whoever is focused).
      // Putting them on every dead line was most of the visual noise.
      if (!out || focus === s.name){
        pts.forEach(function(p, pi){
          if (pi === pts.length - 1) return;  // the endpoint gets its own marker
          svg.appendChild(el('circle', {cx:p[0], cy:p[1], r:3.3,
            fill:color, class:'fep-dot' + (dimmed ? ' fep-dimmed' : '')}));
        });
      }

      // Marker on the final point: a cross where a campaign ended.
      if (out){
        var k = 4.2;
        ['M' + (last[0]-k) + ',' + (last[1]-k) + 'L' + (last[0]+k) + ',' + (last[1]+k),
         'M' + (last[0]+k) + ',' + (last[1]-k) + 'L' + (last[0]-k) + ',' + (last[1]+k)
        ].forEach(function(d){
          svg.appendChild(el('path', {d:d, stroke:color, 'stroke-width':2.2, 'stroke-linecap':'round',
            class:'fep-dot' + (dimmed ? ' fep-dimmed' : '')}));
        });
      } else {
        svg.appendChild(el('circle', {cx:last[0], cy:last[1], r:4.2, fill:color,
          class:'fep-dot' + (dimmed ? ' fep-dimmed' : '')}));
      }

    });
  }

  // --- interaction: find the NEAREST line, not every line -------------------
  function nearest(evt){
    var S = scales(), r = svg.getBoundingClientRect();
    var pt = (evt.touches ? evt.touches[0] : evt);
    var mx = (pt.clientX - r.left) / r.width * W;
    var my = (pt.clientY - r.top) / r.height * H;
    var i = Math.round((mx - S.left) / ((W - S.left - S.right) / Math.max(1, D.weeks.length - 1)));
    i = Math.max(0, Math.min(D.weeks.length - 1, i));

    var best = null, bestD = 1e9;
    D.series.forEach(function(s){
      var v = valueAt(s, i);
      if (v === null || v === undefined) return;
      if (s.eliminatedAt !== null && s.eliminatedAt !== undefined
          && D.weeks[i] > s.eliminatedAt) return;
      var d = Math.abs(S.y(v) - my);
      if (d < bestD){ bestD = d; best = s; }
    });
    return (best && bestD < 40) ? {s:best, i:i} : null;
  }

  function showTip(hit, evt){
    if (!hit){ tip.style.opacity = 0; return; }
    var s = hit.s, i = hit.i;
    var v = s.values[i], prev = i > 0 ? s.values[i-1] : null;
    var delta = (prev === null || prev === undefined || v === null) ? null : (v - prev);
    var rank = D.ranks[i][s.name];
    var gm = D.games[i];
    tip.innerHTML =
      '<b style="color:' + (s.line || s.color) + '">' + s.name + '</b>' +
      '<span class="game">' + D.labels[i] + (gm && gm.label && gm.label !== 'Bye'
        ? '  ' + gm.label + (gm.result ? '  (' + gm.result + ')' : '') : '  bye week') +
      '</span>' +
      '<div class="row"><span>Odds</span><span>' + (v === null ? '--' : v.toFixed(1) + '%') + '</span></div>' +
      '<div class="row"><span>Rank</span><span>' + rank + ' of ' + D.series.length + '</span></div>' +
      (delta === null ? '' :
      '<div class="row"><span>Change</span><span style="color:' +
        (delta > 0 ? '#3ddc97' : (delta < 0 ? '#ff7a7a' : 'inherit')) + '">' +
        (delta > 0 ? '+' : '') + delta.toFixed(1) + '</span></div>');

    var r = svg.getBoundingClientRect(), rr = root.getBoundingClientRect();
    var S = scales();
    var x = S.x(i) / W * r.width + (r.left - rr.left);
    var y = S.y(s.values[i]) / H * r.height + (r.top - rr.top);
    tip.style.opacity = 1;
    tip.style.left = Math.max(4, Math.min(rr.width - tip.offsetWidth - 4, x + 14)) + 'px';
    tip.style.top = Math.max(4, y - tip.offsetHeight - 10) + 'px';
  }

  function onMove(evt){
    var hit = nearest(evt);
    hover = hit ? hit.s.name : null;
    if (!pinned) draw();
    showTip(hit, evt);
  }
  function onLeave(){ hover = null; tip.style.opacity = 0; if (!pinned) draw(); }

  svg.addEventListener('mousemove', onMove);
  svg.addEventListener('mouseleave', onLeave);
  svg.addEventListener('touchstart', function(e){ onMove(e); }, {passive:true});
  svg.addEventListener('touchmove', function(e){ onMove(e); }, {passive:true});
  svg.addEventListener('touchend', onLeave);

  // roster chips double as the mobile legend and as tap-to-isolate.
  // Sorted by current standing, then alphabetically, so the chip order reads
  // as the leaderboard rather than as an arbitrary roster.
  var roster = root.querySelector('[data-roster]');
  D.series.slice().sort(function(a, b){
    var d = (b.current || 0) - (a.current || 0);
    return d !== 0 ? d : a.name.localeCompare(b.name);
  }).forEach(function(s){
    var out = s.eliminatedAt !== null && s.eliminatedAt !== undefined;
    var chip = document.createElement('button');
    chip.className = 'fep-chip'; chip.type = 'button';
    chip.setAttribute('aria-pressed', 'false');
    if (out) chip.setAttribute('data-out', '1');
    if (out) { chip.style.color = ''; }
    else { chip.style.background = s.color; chip.style.color = s.ink; chip.style.borderColor = 'transparent'; }
    chip.innerHTML = (out ? '<span class="fep-swatch" style="background:' + D.dim + '"></span>' : '') +
      s.name + (out ? '' : ' <span style="opacity:.8;font-variant-numeric:tabular-nums">' +
      (s.current || 0).toFixed(1) + '%</span>');
    chip.addEventListener('click', function(){
      pinned = (pinned === s.name) ? null : s.name;
      Array.prototype.forEach.call(roster.children, function(c){
        c.setAttribute('aria-pressed', String(c === chip && pinned !== null));
      });
      tip.style.opacity = 0;
      draw();
    });
    roster.appendChild(chip);
  });

  draw();
  if (window.ResizeObserver) new ResizeObserver(function(){ draw(); }).observe(root);
})();
</script>
</div>
"""
