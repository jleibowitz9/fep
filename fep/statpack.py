"""
The weekly stat pack.

Renders everything in analytics.py as markdown you can read while drafting the
newsletter. It is an INPUT to the newsletter, not a replacement: it hands over
verified numbers and leaves the storytelling alone.

House rule, enforced by a test: no em dashes and no en dashes, anywhere.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import analytics, engine, season as season_mod

BANNED = ("—", "–")  # em dash, en dash


def _pct(value: Optional[float], digits: int = 1) -> str:
    return "--" if value is None else "{:.{}f}%".format(value, digits)


def _signed(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return "{}{:.1f}".format("+" if value > 0 else "", value)


def _table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return "_(nothing to report)_\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out) + "\n"


def render(season: dict, board: engine.Board, week: int,
           pack: Optional[dict] = None) -> str:
    """The full weekly pack as markdown."""
    pack = pack or analytics.full_pack(season, board, week)
    year = season["year"]
    lines: List[str] = []
    add = lines.append

    label = "Week {}".format(week) if week else "Preseason"
    add("# {} FEP | {} stat pack".format(year, label))
    add("")
    add("_{:,} remaining outcomes. {} still alive. Generated from the model, "
        "not from memory._".format(pack["remaining_outcomes"],
                                   pack["concentration"]["alive"]))
    if pack["is_bye"]:
        add("")
        add("**Bye week.** No new result, but the ESPN weights moved, so the "
            "board moved with them.")
    add("")

    # ---- the board -------------------------------------------------------
    add("## The Standings")
    add("")
    deltas = pack["heat_check"]["deltas"]
    rows = []
    for position, name in enumerate(pack["ranked"], start=1):
        odds = pack["board"][name]
        rows.append([
            position if odds > 0 else "--",
            "**{}**".format(name),
            _pct(odds),
            _signed(deltas.get(name)) if deltas else "--",
            pack["current_points"][name],
            "{:.2f}".format(pack["expected_finish"][name]),
            "{}-{}".format(pack["range"][name]["worst"], pack["range"][name]["best"]),
        ])
    add(_table(["#", "Competitor", "Odds", "Chg", "Correct", "Exp. final", "Floor-Ceiling"], rows))

    # ---- heat check ------------------------------------------------------
    heat = pack["heat_check"]
    if heat["baseline_week"] is not None:
        add("## Heat Check")
        add("")
        add("_Change since Week {}._".format(heat["baseline_week"]))
        add("")
        up = ["{} ({})".format(n, _signed(heat["deltas"][n])) for n in heat["up"][:5]]
        down = ["{} ({})".format(n, _signed(heat["deltas"][n])) for n in heat["down"][:5]]
        add("- Up: {}".format(", ".join(up) if up else "nobody"))
        add("- Down: {}".format(", ".join(down) if down else "nobody"))
        add("")

    # ---- decision tree ---------------------------------------------------
    deciding = pack["deciding_layer"]
    add("## Decision Tree")
    add("")
    add("_Of the {:,} ways the rest of the season can go, here is how the title "
        "gets decided._".format(pack["remaining_outcomes"]))
    add("")
    add(_table(
        ["Deciding layer", "Share of outcomes",
         "Chg vs Wk {}".format(deciding["baseline_week"])
         if deciding["baseline_week"] is not None else "Chg"],
        [[r["layer"], _pct(r["share"]), _signed(r["delta"])] for r in deciding["rows"]],
    ))

    # ---- leverage --------------------------------------------------------
    leverage = pack["next_game_leverage"]
    if leverage:
        add("## Leverage Index: {} Preview".format(leverage["label"]))
        add("")
        add("**{}** of all leaderboard equity swings on this one result."
            .format(_pct(leverage["leverage"])))
        add("")
        swing = {n: round(leverage["if_win"][n] - leverage["if_lose"][n], 1)
                 for n in leverage["if_win"]}
        helped = sorted([n for n in swing if swing[n] > 0], key=lambda n: -swing[n])[:4]
        hurt = sorted([n for n in swing if swing[n] < 0], key=lambda n: swing[n])[:4]
        add("- A win helps: {}".format(
            ", ".join("{} ({})".format(n, _signed(swing[n])) for n in helped) or "nobody"))
        add("- A win hurts: {}".format(
            ", ".join("{} ({})".format(n, _signed(swing[n])) for n in hurt) or "nobody"))
        add("")
        add(_table(["Competitor", "If W", "If L", "Swing"],
                   [[n, _pct(leverage["if_win"][n]), _pct(leverage["if_lose"][n]),
                     _signed(swing[n])]
                    for n in sorted(swing, key=lambda n: -abs(swing[n]))[:6]]))

    if pack["leverage_ranking"]:
        add("### Biggest remaining leverage games")
        add("")
        add(_table(["Game", "Leverage"],
                   [[r["label"], _pct(r["leverage"])] for r in pack["leverage_ranking"]]))

    # ---- counterfactual --------------------------------------------------
    counter = pack["counterfactual"]
    if counter:
        add("## The Counterfactual")
        add("")
        add("_If {} had been an {} instead of a {}:_".format(
            counter["label"],
            "L" if counter["actual"] == "W" else "W",
            counter["actual"]))
        add("")
        alt = counter["board"]
        add(", ".join("{} {}".format(n, _pct(alt[n]))
                      for n in sorted(alt, key=lambda n: -alt[n]) if alt[n] > 0))
        add("")

    # ---- eliminations ----------------------------------------------------
    elim = pack["elimination"]
    add("## Elimination Watch")
    add("")
    if elim["eliminated"]:
        add("- Already out: {}".format(", ".join(elim["eliminated"])))
    else:
        add("- Nobody is eliminated yet.")
    if elim["next_game_label"]:
        add("- A **{}** win eliminates: {}".format(
            elim["next_game_label"],
            ", ".join(elim["eliminated_by_win"]) or "nobody"))
        add("- A **{}** loss eliminates: {}".format(
            elim["next_game_label"],
            ", ".join(elim["eliminated_by_loss"]) or "nobody"))
    add("")

    # ---- differentiation -------------------------------------------------
    add("## Differentiation")
    add("")
    add("_Being right is only half of it. Being right in the same way as someone "
        "who beats you on tiebreakers is how campaigns die._")
    add("")
    diff = pack["differentiation"]
    rows = [[n, diff[n]["mean_distance"], diff[n]["nearest"],
             "{} of {}".format(diff[n]["nearest_shared"], diff[n]["remaining_games"])]
            for n in sorted(diff, key=lambda n: -diff[n]["mean_distance"])]
    add(_table(["Competitor", "Avg. distance from field", "Closest rival",
                "Remaining picks shared"], rows))

    if pack["twins"]:
        add("### Effectively identical from here")
        add("")
        for twin in pack["twins"][:6]:
            a, b = twin["pair"]
            add("- **{}** and **{}** differ on {} remaining game(s). "
                "Predicted records {}-{} and {}-{}, points guesses {} and {}."
                .format(a, b, twin["distance"],
                        twin["predicted_wins"][0], 17 - twin["predicted_wins"][0],
                        twin["predicted_wins"][1], 17 - twin["predicted_wins"][1],
                        twin["points_guess"][0], twin["points_guess"][1]))
        add("")

    # ---- the field -------------------------------------------------------
    add("## Circle These Games")
    add("")
    add("_Where the field disagrees. Consensus 1.00 means everyone picked the same way._")
    add("")
    add(_table(["Game", "W", "L", "Consensus", "ESPN", "Field vs ESPN"],
               [[r["label"], r["picked_win"], r["picked_loss"],
                 "{:.2f}".format(r["consensus"]),
                 _pct(None if r["espn_weight"] is None else r["espn_weight"] * 100),
                 _signed(None if r["field_vs_espn"] is None else r["field_vs_espn"] * 100)]
                for r in pack["chalk"][:8]]))

    # ---- meta ------------------------------------------------------------
    conc = pack["concentration"]
    cal = pack["calibration"]
    add("## Under the Hood")
    add("")
    add("- **How open is it:** effective field of {} competitors "
        "({} technically alive, leader at {}).".format(
            conc["effective_field"], conc["alive"], _pct(conc["leader_share"])))
    if cal.get("games"):
        add("- **Is ESPN any good this year:** Brier score {} over {} games "
            "({} than a coin flip at 0.25). Straight up it has called {} of {} "
            "({}). It projected {} wins by now; the Eagles have {}.".format(
                cal["brier"], cal["games"],
                "better" if cal["beats_coinflip"] else "worse",
                cal["straight_up_correct"], cal["games"], _pct(cal["straight_up_pct"]),
                cal["mean_predicted_wins"], cal["actual_wins"]))
    points = pack["points_model"]
    add("- **Points tiebreaker model:** Normal centred on {:.0f} with spread {:.0f} "
        "({} model, {} games of scoring so far).".format(
            points["mean"], points["sd"], points["model"], points["games_played"]))

    volatility = pack["volatility"]
    if volatility:
        movers = sorted(volatility, key=lambda n: -volatility[n]["total_movement"])[:3]
        add("- **Most volatile so far:** {}.".format(", ".join(
            "{} ({} points of total movement, peaked at {} in Week {})".format(
                n, volatility[n]["total_movement"], _pct(volatility[n]["peak"]),
                volatility[n]["peak_week"]) for n in movers)))
    add("")

    text = "\n".join(lines)
    for bad in BANNED:
        text = text.replace(bad, ", ")
    return text


def write(season: dict, board: engine.Board, week: int, path: str,
          pack: Optional[dict] = None) -> str:
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = render(season, board, week, pack)
    with open(path, "w") as fh:
        fh.write(content)
    return path
