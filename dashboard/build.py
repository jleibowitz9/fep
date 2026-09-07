#!/usr/bin/env python3
"""
Build the FEP Control dashboard into a single self-contained HTML file.

    python3 dashboard/build.py              # live 2026 season
    python3 dashboard/build.py --mock FILE  # a prepared dataset (the prototype)

The dashboard is deliberately one file with the week's data baked in. That
means it opens with a double click, works offline, and shows exactly the week
it was built for. Rebuild it, and it shows the new week.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

TEMPLATE = os.path.join(HERE, "template.html")
OUTPUT = os.path.join(HERE, "index.html")


def collect(year: int, week: int = None) -> dict:
    """Everything the dashboard needs, from the live season file."""
    from fep import analytics, history, season as season_mod

    season = season_mod.load(year)
    if not season_mod.has_picks(season):
        raise SystemExit(
            "No picks loaded for {}. Run: python3 cli.py picks <file.csv>\n"
            "Or build the prototype: python3 dashboard/build.py --mock /tmp/mock.json"
            .format(year))

    week = week if week is not None else season_mod.current_nfl_week(season)
    board = season_mod.run(season, through_week=week)
    pack = analytics.full_pack(season, board, week, through_week=week,
                              leverage_limit=17)

    # Everything the page ships must describe the same week the board does. The
    # payload used to take games, snapshots and retrospective leverage straight
    # off the live season, so a historical build showed an old board beside
    # today's results. `pin` is the single place that decides what "as of week
    # N" means, and the pack is already built from it.
    view = analytics.pin(season, week)

    # A competitor with no history genuinely has no career record -- a rookie in
    # the pool is not a defect. Anything else is, so only the lookup miss is
    # tolerated, and it is recorded rather than swallowed.
    career, personality, gaps = {}, {}, []
    for name in season["roster"]:
        try:
            career[name] = history.career(name)
            personality[name] = history.pick_personality(name)
        except KeyError:
            gaps.append(name)
    if gaps:
        print("  note: no history for {}".format(", ".join(gaps)), file=sys.stderr)

    return {
        "year": year, "week": week,
        "generated": season.get("updated_at", "")[:10],
        "games": [{"i": g["index"], "week": g["nfl_week"], "label": g["label"],
                   "result": g["result"], "weight": g["weight"],
                   "points": g["points_for"], "division": g["division"],
                   "resultSource": g.get("result_source"),
                   "weightSource": g.get("weight_source"), "date": g["date"]}
                  for g in view["games"]],
        "roster": season["roster"], "picks": season["picks"],
        # Keyed by name. The dashboard used to index a twelve-colour array by
        # roster position, which is the bug that renamed everyone's colour the
        # moment a thirteenth competitor sorted into the middle.
        "colors": chart_colors(season),
        "guesses": season["points_guess"],
        "board": pack["board"], "straight": pack["straight"],
        "correct": pack["current_points"], "ranked": pack["ranked"],
        "heat": pack["heat_check"], "deciding": pack["deciding_layer"],
        "elim": pack["elimination"], "diff": pack["differentiation"],
        "twins": pack["twins"], "expected": pack["expected_finish"],
        "span": pack["range"], "chalk": pack["chalk"],
        "conc": pack["concentration"], "vol": pack["volatility"],
        "cal": pack["calibration"], "counter": pack["counterfactual"],
        "leverage": pack["leverage_ranking"], "nextLev": pack["next_game_leverage"],
        "pointsModel": pack["points_model"],
        "whatif": pack["whatif"],
        "retro": pack["retrospective_leverage"],
        "career": career, "personality": personality,
        "snapshots": [{"week": s["week"], "weighted": s["weighted"],
                       "correct": s["current_points"], "deciding": s["deciding"],
                       "outcomes": s["remaining_outcomes"]}
                      for s in view.get("snapshots", [])],
        "outcomes": board.remaining_outcomes,
        "champions": history.champions(),
    }


def chart_colors(season: dict) -> dict:
    from fep import chart
    return chart.colors_for(season["roster"], season.get("colors"))


def chart_script(data: dict) -> str:
    """The real chart renderer, mounted inside the dashboard's Chart tab."""
    try:
        from fep import chart
    except Exception:
        return ""
    board = {s["week"]: s["weighted"] for s in data["snapshots"]}
    if not board:
        return ""
    games = {g["week"]: {"label": g["label"], "result": g["result"]}
             for g in data["games"]}
    html = chart.render(weeks=sorted(board), board_by_week=board,
                        roster=data["roster"], games=games,
                        year=data["year"], upto_week=data["week"],
                        standalone=False)
    # The chart markup contains its own <script> tags. Embedding it inside a
    # <script> without escaping the closing sequence ends the outer tag early
    # and dumps the rest of the code onto the page as text.
    payload = json.dumps(html).replace("</", "<\\/")
    # innerHTML inserts <script> tags inert, so the executable ones have to be
    # recreated. Only those: recreating the application/json data block would
    # drop its data-payload attribute (attributes are not carried over), and the
    # chart would then be unable to find its own data.
    return ("(function(){var m=document.getElementById('chartMount');"
            "if(!m) return;"
            "m.innerHTML=%s;"
            "var s=m.querySelectorAll('script');"
            "for(var i=0;i<s.length;i++){"
            "  var t=(s[i].type||'').toLowerCase();"
            "  if(t && t.indexOf('javascript')===-1) continue;"
            "  var n=document.createElement('script');"
            "  n.textContent=s[i].textContent;"
            "  s[i].parentNode.replaceChild(n,s[i]);"
            "}})();" % payload)


def build(data: dict, output: str = OUTPUT) -> str:
    with open(TEMPLATE) as fh:
        template = fh.read()
    page = (template
            .replace("__DATA__", json.dumps(data))
            .replace("__CHART__", chart_script(data)))
    with open(output, "w") as fh:
        fh.write(page)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--mock", help="a prepared JSON dataset")
    parser.add_argument("--out", default=OUTPUT)
    args = parser.parse_args()

    data = json.load(open(args.mock)) if args.mock else collect(args.year, args.week)
    path = build(data, args.out)
    size = os.path.getsize(path) / 1024
    print("Built {} ({:.0f} KB)".format(os.path.relpath(path, ROOT), size))
    print("  {} week {}, {} competitors, {} snapshots".format(
        data["year"], data["week"], len(data["roster"]), len(data["snapshots"])))
    print("\n  open '{}'".format(path))


if __name__ == "__main__":
    main()
