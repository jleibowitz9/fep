"""
Derived statistics for the FEP newsletter.

Nothing here is stored anywhere. Every function recomputes from the season's
facts, which is cheap now that a full board takes about a third of a second.
That is deliberate: a cached stat is a stat that can silently disagree with the
board after a result is corrected.

The segments the newsletter already runs:
    heat_check          week-over-week risers and fallers
    leverage_for_game   how much one game swings the pool
    rank_leverage       every remaining game, ranked
    individual_leverage who a win helps and who it hurts
    counterfactual      the board under the opposite result
    deciding_layer      share of outcomes settled outright vs by each tiebreaker
    elimination_watch   who is out, who is one loss from out

New, for storylines that previously needed ad-hoc help:
    differentiation     how much each pick sheet still differs from the field
    expected_finish     probability-weighted final correct picks
    range_of_outcomes   best and worst case finish
    retrospective_leverage  which past game cost each competitor the most
    chalk_index         where the field agrees, and where it splits
    volatility          whose odds have swung the most
    concentration       how wide open the race is, as one number
    espn_calibration    is the matchup predictor any good this year
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from . import engine, season as season_mod

UNPLAYED = engine.UNPLAYED


def _run(season: dict, results: List[str]) -> engine.Board:
    return season_mod.run(season, results_override=results, skip_validation=True)


def pin(season: dict, through_week: Optional[int]) -> dict:
    """The season as it stood at the end of an NFL week.

    Masks later games back to unplayed AND drops later snapshots. Doing only the
    first (which is what full_pack used to do) leaves every snapshot-derived
    statistic reading the future: a Week 1 pack reported Week 2's volatility as
    "current". Anything that pins a board must pin through this, so the board
    and every number beside it describe the same moment.
    """
    if through_week is None:
        return season
    pinned = dict(season)
    pinned["games"] = [
        dict(g, result=engine.UNPLAYED, points_for=None)
        if g["nfl_week"] > through_week else g
        for g in season["games"]
    ]
    pinned["snapshots"] = [
        snap for snap in season.get("snapshots", [])
        if snap.get("week", 0) <= through_week
    ]
    return pinned


# ---------------------------------------------------------------------------
# Heat Check
# ---------------------------------------------------------------------------

def heat_check(season: dict, board: engine.Board, week: int) -> dict:
    """Change in each competitor's odds since the previous snapshot.

    The newsletter renders this as the 🔥 up / 🧊 down segment.
    """
    previous = season_mod.previous_snapshot(season, week)
    if previous is None:
        return {"baseline_week": None, "deltas": {}, "up": [], "down": [], "flat": []}

    baseline = previous["weighted"]
    deltas = {
        name: round(board.weighted[name] - baseline.get(name, 0.0), 1)
        for name in board.order
    }
    up = sorted([n for n in deltas if deltas[n] > 0], key=lambda n: -deltas[n])
    down = sorted([n for n in deltas if deltas[n] < 0], key=lambda n: deltas[n])
    flat = [n for n in deltas if deltas[n] == 0]
    return {"baseline_week": previous["week"],
            # Whether the baseline really is last week. standings_table already
            # refuses to report a change across a gap, on the grounds that a
            # two-week move printed as a one-week move is worse than printing
            # nothing. This segment cannot refuse -- the newsletter needs its
            # risers -- so it labels the gap instead, and the two surfaces stop
            # disagreeing about what "change" means.
            "baseline_is_previous_week": previous["week"] == week - 1,
            "deltas": deltas, "up": up, "down": down, "flat": flat}


# ---------------------------------------------------------------------------
# Leverage Index
# ---------------------------------------------------------------------------

def leverage_for_game(season: dict, game_index: int, results: Optional[List[str]] = None) -> dict:
    """How much of the pool's equity swings on one game.

    Run the board twice, once forcing a win and once a loss, and measure how
    much probability changes hands. Halved because every point one competitor
    gains, another loses.
    """
    base = list(results if results is not None else season_mod.results(season))
    win, lose = list(base), list(base)
    win[game_index], lose[game_index] = engine.WIN, engine.LOSS

    board_win, board_lose = _run(season, win), _run(season, lose)
    swing = sum(
        abs(board_win.weighted[n] - board_lose.weighted[n]) for n in board_win.order
    ) / 2.0
    return {
        "game_index": game_index,
        "label": season["games"][game_index]["label"],
        "leverage": round(swing, 1),
        "if_win": {n: round(board_win.weighted[n], 1) for n in board_win.order},
        "if_lose": {n: round(board_lose.weighted[n], 1) for n in board_lose.order},
    }


def whatif_boards(season: dict) -> Dict[str, dict]:
    """Every game's W and L board, keyed by game index as a string.

    This is what the dashboard's What If tab reads. For an unplayed game the two
    boards are the two ways it can still go; for a played one, the board that
    did happen sits alongside the season that did not.

    Keys are strings because this crosses into JSON, where they would become
    strings anyway. Making that explicit here keeps the Python and the shipped
    payload the same shape.
    """
    results = season_mod.results(season)
    out: Dict[str, dict] = {}
    for i, actual in enumerate(results):
        pair = leverage_for_game(season, i, results=results)
        out[str(i)] = {
            engine.WIN: pair["if_win"],
            engine.LOSS: pair["if_lose"],
            "actual": actual,
        }
    return out


def individual_leverage(season: dict, game_index: int) -> Dict[str, float]:
    """Signed swing per competitor. Positive means an Eagles win helps them."""
    result = leverage_for_game(season, game_index)
    return {
        name: round(result["if_win"][name] - result["if_lose"][name], 1)
        for name in result["if_win"]
    }


def rank_leverage(season: dict, limit: Optional[int] = None) -> List[dict]:
    """Every remaining game, ranked by how much it matters."""
    results = season_mod.results(season)
    rows = [
        leverage_for_game(season, i, results)
        for i, r in enumerate(results) if r == UNPLAYED
    ]
    rows.sort(key=lambda row: -row["leverage"])
    return rows[:limit] if limit else rows


def counterfactual(season: dict, game_index: Optional[int] = None) -> Optional[dict]:
    """The board had the most recent completed game gone the other way."""
    results = season_mod.results(season)
    if game_index is None:
        played = [i for i, r in enumerate(results) if r != UNPLAYED]
        if not played:
            return None
        game_index = played[-1]

    actual = results[game_index]
    if actual == UNPLAYED:
        return None
    if actual == engine.TIE:
        # A tie has no single counterfactual: it could have gone either way, and
        # it awarded nobody anything, so "the season that did not happen" is not
        # one season. The What If tab covers both branches individually.
        return None
    flipped = list(results)
    flipped[game_index] = engine.LOSS if actual == engine.WIN else engine.WIN

    board = _run(season, flipped)
    return {
        "game_index": game_index,
        "label": season["games"][game_index]["label"],
        "actual": actual,
        "hypothetical": flipped[game_index],
        "board": {n: round(board.weighted[n], 1) for n in board.order},
    }


def counterfactual_for_week(season: dict, week: int) -> Optional[dict]:
    """The board had THIS week's game gone the other way, or None.

    This is what the weekly snapshot records and the CMS publishes for the
    standings carousel. Four cases have no counterfactual and return None:
    week 0 and a bye (no game), an unplayed game, and a tie -- a tie could have
    gone either way and awarded nobody anything, so "the season that did not
    happen" is not one season. Every column derived from this is blank then;
    nothing guesses a W or an L.

    Pinned through the week, so a Thursday result from the week after cannot
    leak in. The flipped game keeps its actual Eagles points in the tiebreaker-3
    model, the same convention as leverage_for_game and whatif_boards.
    """
    index = season_mod.game_index_for_week(season, week)
    if index is None:
        return None
    return counterfactual(pin(season, week), game_index=index)


def retrospective_leverage(season: dict) -> List[dict]:
    """For each completed game, how much the result moved each competitor.

    The regret engine: "that Week 4 loss cost Nathan 18 points of equity."
    """
    results = season_mod.results(season)
    actual_board = _run(season, results)  # same in every comparison; compute once
    rows = []
    for i, actual in enumerate(results):
        if actual in (UNPLAYED, engine.TIE):
            continue  # a tie moved nobody, so there is no regret to measure
        flipped = list(results)
        flipped[i] = engine.LOSS if actual == engine.WIN else engine.WIN
        other_board = _run(season, flipped)
        swing = {
            n: round(actual_board.weighted[n] - other_board.weighted[n], 1)
            for n in actual_board.order
        }
        rows.append({
            "game_index": i,
            "label": season["games"][i]["label"],
            "result": actual,
            "swing": swing,
            "magnitude": round(sum(abs(v) for v in swing.values()) / 2.0, 1),
        })
    return rows


# ---------------------------------------------------------------------------
# Decision Tree / Deciding Layer
# ---------------------------------------------------------------------------

def deciding_layer(season: dict, board: engine.Board, week: int) -> dict:
    """Share of remaining outcomes settled outright vs by each tiebreaker.

    Falls straight out of the simulation pass. The newsletter renders it as a
    table with a delta against the previous week.
    """
    from . import chart
    previous = season_mod.previous_snapshot(season, week)
    prior = (previous or {}).get("deciding", {})
    # One shape, shared with the published chart data (chart.deciding_rows),
    # so the stat pack and the Framer component cannot describe a week's
    # tiebreaker split differently.
    return {"rows": chart.deciding_rows(board.deciding, prior),
            "baseline_week": (previous or {}).get("week")}


# ---------------------------------------------------------------------------
# Eliminations
# ---------------------------------------------------------------------------

def elimination_watch(season: dict, board: engine.Board) -> dict:
    """Who is mathematically out, and who goes out on the next result."""
    results = season_mod.results(season)
    # "Mathematically eliminated" is a statement about what the rules permit, so
    # it counts outcomes rather than probability. Zero weighted equity with a
    # surviving path is a different, weaker claim, and gets its own list.
    out = board.eliminated()
    dim = board.effectively_eliminated()
    alive = [n for n in board.order if n not in out]

    next_index = engine.next_game_index(results)
    on_the_brink = {"win": [], "lose": []}
    if next_index is not None:
        for outcome, key in ((engine.WIN, "win"), (engine.LOSS, "lose")):
            forced = list(results)
            forced[next_index] = outcome
            forced_board = _run(season, forced)
            gone = set(forced_board.eliminated())
            on_the_brink[key] = [n for n in alive if n in gone]

    return {
        "eliminated": out,
        "effectively_eliminated": dim,
        "alive": alive,
        "next_game_index": next_index,
        "next_game_label": season["games"][next_index]["label"] if next_index is not None else None,
        "eliminated_by_win": on_the_brink["win"],
        "eliminated_by_loss": on_the_brink["lose"],
    }


# ---------------------------------------------------------------------------
# Differentiation: the "statistically redundant" problem
# ---------------------------------------------------------------------------

def differentiation(season: dict, board: engine.Board) -> Dict[str, dict]:
    """How much each competitor's REMAINING sheet still differs from the field.

    Two things kill a FEP campaign: being wrong, and being right in exactly the
    same way as someone who beats you on tiebreakers. This measures the second.

    mean_distance   average disagreements with the rest of the field on
                    remaining games (higher = more differentiated)
    nearest         the competitor with the most similar remaining sheet
    nearest_shared  how many remaining games they agree on
    """
    results = season_mod.results(season)
    remaining = [i for i, r in enumerate(results) if r == UNPLAYED]
    picks = season["picks"]
    names = board.order

    rows: Dict[str, dict] = {}
    for name in names:
        distances = {}
        for other in names:
            if other == name:
                continue
            distances[other] = sum(
                1 for i in remaining if picks[name][i] != picks[other][i]
            )
        if not distances:
            continue
        nearest = min(distances, key=lambda o: (distances[o], o))
        rows[name] = {
            "mean_distance": round(sum(distances.values()) / len(distances), 2),
            "nearest": nearest,
            "nearest_distance": distances[nearest],
            "nearest_shared": len(remaining) - distances[nearest],
            "remaining_games": len(remaining),
        }
    return rows


def twin_check(season: dict, threshold: int = 1) -> List[dict]:
    """Pairs whose remaining sheets are nearly identical.

    These are the pairs where the tiebreakers, not the picks, will decide it.
    """
    results = season_mod.results(season)
    remaining = [i for i, r in enumerate(results) if r == UNPLAYED]
    picks = season["picks"]
    names = list(picks)

    pairs = []
    for a_index, a in enumerate(names):
        for b in names[a_index + 1:]:
            distance = sum(1 for i in remaining if picks[a][i] != picks[b][i])
            if distance <= threshold:
                pairs.append({
                    "pair": (a, b),
                    "distance": distance,
                    "predicted_wins": (picks[a].count("W"), picks[b].count("W")),
                    "points_guess": (season["points_guess"][a], season["points_guess"][b]),
                })
    pairs.sort(key=lambda p: p["distance"])
    return pairs


# ---------------------------------------------------------------------------
# Expected finish and range
# ---------------------------------------------------------------------------

def expected_finish(season: dict, board: engine.Board) -> Dict[str, float]:
    """Probability-weighted final correct-pick total.

    A cleaner read on "who is actually picking well" than the win percentage,
    which is distorted by tiebreaker position.
    """
    results = season_mod.results(season)
    weights = season_mod.weights(season)
    remaining = [i for i, r in enumerate(results) if r == UNPLAYED]
    picks = season["picks"]

    out = {}
    for name in board.order:
        expected = float(board.current_points[name])
        for i in remaining:
            p_win = float(weights[i])
            expected += p_win if picks[name][i] == engine.WIN else (1.0 - p_win)
        out[name] = round(expected, 2)
    return out


def range_of_outcomes(season: dict, board: engine.Board) -> Dict[str, dict]:
    """Best and worst possible final correct-pick totals."""
    results = season_mod.results(season)
    remaining = sum(1 for r in results if r == UNPLAYED)
    return {
        name: {
            "current": board.current_points[name],
            "worst": board.current_points[name],
            "best": board.current_points[name] + remaining,
        }
        for name in board.order
    }


# ---------------------------------------------------------------------------
# The field
# ---------------------------------------------------------------------------

def chalk_index(season: dict) -> List[dict]:
    """For each remaining game, how split the field is.

    consensus 1.0 means everyone picked the same way. The games near 0.5 are the
    "circle these games" callouts, because they are where the pool actually
    separates.
    """
    results = season_mod.results(season)
    weights = season_mod.weights(season)
    picks = season["picks"]
    total = len(picks)

    rows = []
    for i, result in enumerate(results):
        if result != UNPLAYED:
            continue
        wins = sum(1 for name in picks if picks[name][i] == engine.WIN)
        rows.append({
            "game_index": i,
            "label": season["games"][i]["label"],
            "picked_win": wins,
            "picked_loss": total - wins,
            "consensus": round(max(wins, total - wins) / total, 2),
            "espn_weight": weights[i],
            # Positive means the field is more optimistic than ESPN.
            "field_vs_espn": None if weights[i] is None
            else round(wins / total - float(weights[i]), 2),
        })
    rows.sort(key=lambda r: r["consensus"])
    return rows


def concentration(board: engine.Board) -> dict:
    """How wide open the race is.

    hhi is the sum of squared shares: 1.0 means one person is a lock, and
    1/N means a perfectly even field. effective_field translates that into
    "how many competitors are really still in this".
    """
    shares = [board.weighted[n] / 100.0 for n in board.order]
    hhi = sum(s * s for s in shares)
    return {
        "hhi": round(hhi, 4),
        "effective_field": round(1.0 / hhi, 2) if hhi > 0 else 0.0,
        "alive": sum(1 for s in shares if s > 0),
        "leader_share": round(max(shares) * 100, 1) if shares else 0.0,
    }


def volatility(season: dict) -> Dict[str, dict]:
    """Whose odds have moved the most across the season so far."""
    snapshots = season.get("snapshots", [])
    if len(snapshots) < 2:
        return {}

    out = {}
    for name in season["roster"]:
        series = [s["weighted"].get(name, 0.0) for s in snapshots]
        moves = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
        peak = max(series)
        out[name] = {
            "peak": round(peak, 1),
            "peak_week": snapshots[series.index(peak)]["week"],
            "low": round(min(series), 1),
            "total_movement": round(sum(moves), 1),
            "biggest_single_move": round(max(moves), 1) if moves else 0.0,
            "current": round(series[-1], 1),
        }
    return out


def espn_calibration(season: dict) -> dict:
    """Brier score of the ESPN matchup predictor against what actually happened.

    0 is perfect, 0.25 is what you get by saying 50/50 every week. A recurring
    meta-stat: is the predictor earning its keep this year.
    """
    played = [
        g for g in season["games"]
        if g["result"] != UNPLAYED and g.get("weight") is not None
    ]
    if not played:
        return {"games": 0}

    errors = []
    right = 0
    for game in played:
        p = float(game["weight"])
        # A tie scores as half a win: the predictor was neither right nor wrong,
        # which is what a 0.5 outcome means to a Brier score. It cannot be
        # called correct straight up either way, so it counts toward neither.
        if game["result"] == engine.TIE:
            errors.append((p - 0.5) ** 2)
            continue
        actual = 1.0 if game["result"] == engine.WIN else 0.0
        errors.append((p - actual) ** 2)
        if (p >= 0.5) == (actual == 1.0):
            right += 1

    brier = sum(errors) / len(errors)
    decided = [g for g in played if g["result"] != engine.TIE]
    return {
        "games": len(played),
        "ties": len(played) - len(decided),
        "brier": round(brier, 4),
        "baseline_coinflip": 0.25,
        "beats_coinflip": brier < 0.25,
        "straight_up_correct": right,
        "straight_up_pct": round(right / len(decided) * 100, 1) if decided else None,
        "mean_predicted_wins": round(sum(float(g["weight"]) for g in played), 2),
        "actual_wins": sum(1 for g in played if g["result"] == engine.WIN),
    }


# ---------------------------------------------------------------------------
# one call for the whole pack
# ---------------------------------------------------------------------------

def full_pack(season: dict, board: engine.Board, week: int,
              leverage_limit: int = 5, through_week: Optional[int] = None) -> dict:
    """Everything the weekly stat pack needs, in one call.

    through_week pins every derived statistic to the same view of the season the
    board used, so leverage and counterfactuals cannot reference a game the
    board has not seen.
    """
    season = pin(season, through_week)
    results = season_mod.results(season)
    next_index = engine.next_game_index(results)

    pack = {
        "week": week,
        "year": season["year"],
        "is_bye": season_mod.is_bye_week(season, week),
        "remaining_outcomes": board.remaining_outcomes,
        "board": {n: round(board.weighted[n], 1) for n in board.order},
        "straight": {n: round(board.straight[n], 1) for n in board.order},
        "current_points": dict(board.current_points),
        "ranked": board.ranked(),
        "heat_check": heat_check(season, board, week),
        "deciding_layer": deciding_layer(season, board, week),
        "elimination": elimination_watch(season, board),
        "differentiation": differentiation(season, board),
        "twins": twin_check(season),
        "expected_finish": expected_finish(season, board),
        "range": range_of_outcomes(season, board),
        "chalk": chalk_index(season),
        "concentration": concentration(board),
        "volatility": volatility(season),
        "calibration": espn_calibration(season),
        "counterfactual": counterfactual(season),
        "points_model": board.points,
        "whatif": whatif_boards(season),
        "retrospective_leverage": retrospective_leverage(season),
    }
    pack["next_game_leverage"] = (
        leverage_for_game(season, next_index) if next_index is not None else None
    )
    pack["leverage_ranking"] = rank_leverage(season, limit=leverage_limit)
    return pack
