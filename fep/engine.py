"""
The FEP simulation engine (Wetzler-Rich-Leibowitz Algorithm 3.0).

Same math as Jacob's 2025 simulator, with three correctness fixes and a much
faster inner loop.

WHAT IT DOES
------------
Enumerate every possible way the remaining games can go (2^k universes), weight
each by how likely it is (the product of the ESPN matchup-predictor
probabilities), decide who wins the pool in each, and add that universe's
probability to the winner. Sum across all universes and you have everyone's
percentage chance to win the season.

TIEBREAKER CASCADE (unchanged in order, applied inside every universe)
  1. Closest predicted final record to the universe's actual record.
  2. Closest predicted NFC East record. Only among survivors of 1.
  3. Closest total-points guess, handled probabilistically: the Eagles' final
     points are modelled as a Normal, and each survivor gets the probability
     mass of the region where their guess is closest.
  4. If all three are exhausted (identical picks, record, division record AND
     points guess) the survivors split evenly.

WHAT CHANGED FROM 2025
----------------------
* FIX: identical points guesses used to split ~97/3 instead of 50/50. The old
  code put the split point exactly on the shared guess, so one competitor took
  all the mass below it and the other all the mass above. Emer and Jen both
  guessed 455 in 2025, so every published board that season carried this. Equal
  guesses are now grouped and share their interval evenly.
* FIX: step 4 above is now explicit rather than an accident of normalization.
* FIX: played games no longer have to be a contiguous prefix. Any subset of
  games can be unplayed, which is what makes retrospective leverage (forcing a
  PAST game the other way) possible.
* SPEED: one pass produces both boards. The old code built the identical tally
  twice, once per board. Picks are bitmasks and scoring is a popcount, so the
  inner loop is integer work instead of string comparison. Measured ~11x.
* NEW: the deciding-layer split (what share of outcomes is settled outright vs
  by each tiebreaker) falls out of the same pass, for free. This is the
  newsletter's Decision Tree segment, which previously had no implementation.

CONVENTION KEPT DELIBERATELY: games are treated as independent, and the points
total is modelled independently of which games are won. Both are simplifications
the family has always used. They keep the math legible and are not worth
breaking a ten-year tradition over.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

WIN, LOSS, UNPLAYED = "W", "L", "A"

# Defaults for the points model. sd_per_game is Jacob's original tunable.
DEFAULT_SD_PER_GAME = 11.0
DEFAULT_PRIOR_PPG = 23.0        # roughly the Eagles' recent scoring rate
DEFAULT_PRIOR_WEIGHT_GAMES = 3.0


class SeasonError(ValueError):
    """Raised when the inputs are not a coherent season."""


# ---------------------------------------------------------------------------
# popcount (Python 3.9 has no int.bit_count)
# ---------------------------------------------------------------------------

_POPCOUNT16 = bytes(bin(i).count("1") for i in range(1 << 16))


def _popcount(x: int) -> int:
    return _POPCOUNT16[x & 0xFFFF] + _POPCOUNT16[x >> 16]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate(
    picks: Dict[str, Sequence[str]],
    results: Sequence[str],
    weights: Sequence[Optional[float]],
    division_indices: Sequence[int],
    points_guess: Dict[str, float],
) -> None:
    """Fail loudly on a malformed season rather than scoring it wrong.

    The 2025 code had no validation at all, so a mis-pasted pick row would
    either throw somewhere deep in the loop or silently score against the wrong
    games.
    """
    games = len(results)
    if games == 0:
        raise SeasonError("season has no games")
    if not picks:
        raise SeasonError("no competitors")

    for name, sheet in picks.items():
        if len(sheet) != games:
            raise SeasonError(
                "{}'s pick sheet has {} entries but the season has {} games".format(
                    name, len(sheet), games
                )
            )
        bad = sorted({p for p in sheet if p not in (WIN, LOSS)})
        if bad:
            raise SeasonError("{}'s picks contain {}; only 'W' and 'L' allowed".format(name, bad))

    bad_results = sorted({r for r in results if r not in (WIN, LOSS, UNPLAYED)})
    if bad_results:
        raise SeasonError("results contain {}; only 'W', 'L', 'A' allowed".format(bad_results))

    if len(weights) != games:
        raise SeasonError("got {} weights for {} games".format(len(weights), games))
    for i, (weight, result) in enumerate(zip(weights, results)):
        if result != UNPLAYED:
            continue  # a played game's weight is irrelevant
        if weight is None:
            raise SeasonError("game {} is unplayed and has no win probability".format(i))
        if not 0.0 <= weight <= 1.0:
            raise SeasonError("game {} has win probability {}, must be 0..1".format(i, weight))

    for index in division_indices:
        if not 0 <= index < games:
            raise SeasonError("division index {} is outside 0..{}".format(index, games - 1))

    missing = sorted(set(picks) - set(points_guess))
    if missing:
        raise SeasonError("no points guess for {}".format(", ".join(missing)))


# ---------------------------------------------------------------------------
# the points tiebreaker
# ---------------------------------------------------------------------------

def points_distribution(
    results: Sequence[str],
    points_scored: Sequence[Optional[int]],
    sd_per_game: float = DEFAULT_SD_PER_GAME,
    prior_ppg: float = DEFAULT_PRIOR_PPG,
    prior_weight_games: float = DEFAULT_PRIOR_WEIGHT_GAMES,
    model: str = "shrunk",
) -> Dict[str, float]:
    """Estimate the Eagles' final points-for as a Normal(mean, sd).

    'legacy' reproduces 2025 exactly: mean is a straight pace projection
    (points so far / games played * total games) and sd is
    sd_per_game * sqrt(games remaining).

    'shrunk' (default) changes only the estimator, not the shape. Pure pace is
    brutal early: after one 24-point game in 2025 it projected the season at
    408, and every tiebreaker leaned on that. Here the per-game rate is shrunk
    toward a prior, and the spread also carries the uncertainty in the rate
    itself instead of pretending the pace is known exactly.

    Note that 'legacy' is exactly 'shrunk' with prior_weight_games = 0, which is
    a useful thing to know when comparing the two.
    """
    total_games = len(results)
    played = [i for i, r in enumerate(results) if r != UNPLAYED]
    scored = [points_scored[i] for i in played if points_scored[i] is not None]
    games_played = len(scored)
    remaining = total_games - len(played)
    points_so_far = float(sum(scored))

    if model == "legacy":
        if games_played == 0:
            mean = prior_ppg * total_games
        else:
            mean = points_so_far / games_played * total_games
        sd = max(1.0, sd_per_game * math.sqrt(max(remaining, 0)))
        return {"mean": mean, "sd": sd, "ppg": mean / total_games, "model": model,
                "games_played": games_played, "points_so_far": points_so_far}

    # Shrink the observed rate toward the prior.
    denominator = prior_weight_games + games_played
    if denominator <= 0:
        ppg = prior_ppg
        denominator = 1.0
    else:
        ppg = (prior_weight_games * prior_ppg + points_so_far) / denominator

    mean = points_so_far + remaining * ppg
    # Two sources of spread: the remaining games themselves, and the fact that
    # we do not actually know the scoring rate.
    var = remaining * sd_per_game ** 2 + (remaining ** 2) * (sd_per_game ** 2) / denominator
    sd = max(1.0, math.sqrt(var))
    return {"mean": mean, "sd": sd, "ppg": ppg, "model": model,
            "games_played": games_played, "points_so_far": points_so_far}


def closest_shares(guesses: Dict[str, float], mean: float, sd: float) -> Dict[str, float]:
    """Probability that each guess ends up closest to the final points total.

    Sort the guesses, give each the Normal mass between the midpoints to its
    neighbours. Competitors who submitted the SAME number are treated as one
    point on the line and split that point's mass evenly, which is the fix for
    the 2025 bug where an exact tie split roughly 97/3.
    """
    if not guesses:
        return {}
    if len(guesses) == 1:
        return {next(iter(guesses)): 1.0}
    if sd <= 0:
        sd = 1.0

    def cdf(x: float) -> float:
        if x == float("-inf"):
            return 0.0
        if x == float("inf"):
            return 1.0
        return 0.5 * (1.0 + math.erf((x - mean) / (sd * math.sqrt(2.0))))

    # Group by identical guess.
    groups: Dict[float, List[str]] = {}
    for name, guess in guesses.items():
        groups.setdefault(float(guess), []).append(name)
    values = sorted(groups)

    shares: Dict[str, float] = {}
    for i, value in enumerate(values):
        left = float("-inf") if i == 0 else (values[i - 1] + value) / 2.0
        right = float("inf") if i == len(values) - 1 else (value + values[i + 1]) / 2.0
        mass = max(0.0, cdf(right) - cdf(left))
        members = groups[value]
        for name in members:
            shares[name] = mass / len(members)

    total = sum(shares.values())
    if total > 0:
        for name in shares:
            shares[name] /= total
    else:
        # Numerically everything landed in a zero-probability tail. Split evenly
        # rather than returning nothing.
        for name in shares:
            shares[name] = 1.0 / len(shares)
    return shares


# ---------------------------------------------------------------------------
# the simulation
# ---------------------------------------------------------------------------

class Board:
    """The result of one simulation."""

    def __init__(self, weighted, straight, deciding, deciding_straight,
                 current_points, remaining_outcomes, points, order):
        self.weighted = weighted                    # name -> % chance to win
        self.straight = straight                    # name -> % of outcomes won
        self.deciding = deciding                    # layer -> % of probability
        self.deciding_straight = deciding_straight  # layer -> % of outcomes
        self.current_points = current_points        # name -> correct picks so far
        self.remaining_outcomes = remaining_outcomes
        self.points = points                        # the points model used
        self.order = order                          # roster order

    def ranked(self):
        return sorted(self.order, key=lambda n: (-self.weighted[n], n))

    def eliminated(self):
        return [n for n in self.order if self.weighted[n] <= 0.0]

    def as_row(self):
        return {n: round(self.weighted[n], 1) for n in self.order}

    def __repr__(self):
        top = ", ".join("{} {:.1f}%".format(n, self.weighted[n]) for n in self.ranked()[:3])
        return "<Board {} outcomes | {}>".format(self.remaining_outcomes, top)


def run(
    picks: Dict[str, Sequence[str]],
    results: Sequence[str],
    weights: Sequence[Optional[float]],
    division_indices: Sequence[int],
    points_guess: Dict[str, float],
    points_scored: Optional[Sequence[Optional[int]]] = None,
    sd_per_game: float = DEFAULT_SD_PER_GAME,
    prior_ppg: float = DEFAULT_PRIOR_PPG,
    prior_weight_games: float = DEFAULT_PRIOR_WEIGHT_GAMES,
    points_model: str = "shrunk",
    points_mean: Optional[float] = None,
    points_sd: Optional[float] = None,
    skip_validation: bool = False,
) -> Board:
    """Run the full simulation and return a Board.

    points_mean / points_sd let a caller pin the points distribution directly,
    which is what the 2025 replay uses to reproduce historical numbers exactly.
    """
    if not skip_validation:
        validate(picks, results, weights, division_indices, points_guess)

    total_games = len(results)
    if points_scored is None:
        points_scored = [None] * total_games

    names = list(picks)
    n_names = len(names)

    remaining = [i for i, r in enumerate(results) if r == UNPLAYED]
    k = len(remaining)
    if k > 24:
        raise SeasonError("{} unplayed games is too many to enumerate".format(k))

    division_set = set(division_indices)

    # Facts about the games already played.
    base = []
    masks = []
    predicted_wins = []
    predicted_div = []
    for name in names:
        sheet = picks[name]
        base.append(sum(1 for i, r in enumerate(results) if r != UNPLAYED and sheet[i] == r))
        mask = 0
        for j, i in enumerate(remaining):
            if sheet[i] == WIN:
                mask |= 1 << j
        masks.append(mask)
        predicted_wins.append(sum(1 for p in sheet if p == WIN))
        predicted_div.append(sum(1 for i in division_indices if sheet[i] == WIN))

    wins_played = sum(1 for r in results if r == WIN)
    div_wins_played = sum(1 for i in division_indices if results[i] == WIN)
    div_mask = 0
    for j, i in enumerate(remaining):
        if i in division_set:
            div_mask |= 1 << j

    # Probability of each of the 2^k universes. Bit j corresponds to remaining[j].
    probabilities = [1.0]
    for j in range(k):
        p = float(weights[remaining[j]])
        probabilities = [v * (1.0 - p) for v in probabilities] + [v * p for v in probabilities]

    # The points model does not depend on which universe we are in (see the
    # module docstring: points are modelled independently of results), so it is
    # computed once.
    if points_mean is None or points_sd is None:
        distribution = points_distribution(
            results, points_scored, sd_per_game=sd_per_game, prior_ppg=prior_ppg,
            prior_weight_games=prior_weight_games, model=points_model,
        )
    else:
        distribution = {"mean": points_mean, "sd": points_sd, "model": "pinned",
                        "ppg": points_mean / max(total_games, 1),
                        "games_played": sum(1 for r in results if r != UNPLAYED),
                        "points_so_far": None}
    mean, sd = distribution["mean"], distribution["sd"]

    guess_by_index = [float(points_guess[name]) for name in names]

    # Tiebreaker-3 shares recur constantly (the same set of competitors ties in
    # many universes), so memoize on the tied set.
    share_cache: Dict[tuple, List[float]] = {}

    def tb3_shares(tied: List[int]) -> List[float]:
        key = tuple(tied)
        cached = share_cache.get(key)
        if cached is None:
            shares = closest_shares({str(i): guess_by_index[i] for i in tied}, mean, sd)
            cached = [shares[str(i)] for i in tied]
            share_cache[key] = cached
        return cached

    weighted = [0.0] * n_names
    straight = [0.0] * n_names
    layers = {"outright": 0.0, "tb1": 0.0, "tb2": 0.0, "tb3": 0.0, "split": 0.0}
    layers_straight = {"outright": 0, "tb1": 0, "tb2": 0, "tb3": 0, "split": 0}

    pop = _POPCOUNT16
    total_outcomes = 1 << k

    for outcome in range(total_outcomes):
        chance = probabilities[outcome]

        # Score everyone: correct future picks = k - hamming(mask, outcome).
        best = -1
        tied: List[int] = []
        for idx in range(n_names):
            x = masks[idx] ^ outcome
            score = base[idx] + k - (pop[x & 0xFFFF] + pop[x >> 16])
            if score > best:
                best = score
                tied = [idx]
            elif score == best:
                tied.append(idx)

        if len(tied) == 1:
            winner = tied[0]
            weighted[winner] += chance
            straight[winner] += 1
            layers["outright"] += chance
            layers_straight["outright"] += 1
            continue

        layer = "tb1"

        # Tiebreaker 1: closest predicted final record.
        actual_wins = wins_played + _popcount(outcome)
        best_diff = min(abs(predicted_wins[i] - actual_wins) for i in tied)
        tied = [i for i in tied if abs(predicted_wins[i] - actual_wins) == best_diff]

        # Tiebreaker 2: closest predicted division record.
        if len(tied) > 1:
            layer = "tb2"
            actual_div = div_wins_played + _popcount(outcome & div_mask)
            best_div = min(abs(predicted_div[i] - actual_div) for i in tied)
            tied = [i for i in tied if abs(predicted_div[i] - actual_div) == best_div]

        if len(tied) == 1:
            winner = tied[0]
            weighted[winner] += chance
            straight[winner] += 1
            layers[layer] += chance
            layers_straight[layer] += 1
            continue

        # Tiebreaker 3: closest total-points guess, probabilistically.
        distinct = {guess_by_index[i] for i in tied}
        layer = "tb3" if len(distinct) > 1 else "split"
        shares = tb3_shares(tied)
        for position, i in enumerate(tied):
            share = shares[position]
            weighted[i] += chance * share
            straight[i] += share
        layers[layer] += chance
        layers_straight[layer] += 1

    scale = 100.0
    weighted_pct = {names[i]: weighted[i] * scale for i in range(n_names)}
    straight_pct = {names[i]: straight[i] / total_outcomes * scale for i in range(n_names)}
    deciding = {key: value * scale for key, value in layers.items()}
    deciding_straight = {
        key: value / total_outcomes * scale for key, value in layers_straight.items()
    }
    current = {names[i]: base[i] for i in range(n_names)}

    return Board(
        weighted=weighted_pct,
        straight=straight_pct,
        deciding=deciding,
        deciding_straight=deciding_straight,
        current_points=current,
        remaining_outcomes=total_outcomes,
        points=distribution,
        order=names,
    )


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def correct_picks_so_far(picks: Dict[str, Sequence[str]], results: Sequence[str]) -> Dict[str, int]:
    return {
        name: sum(1 for i, r in enumerate(results) if r != UNPLAYED and sheet[i] == r)
        for name, sheet in picks.items()
    }


def next_game_index(results: Sequence[str]) -> Optional[int]:
    for i, r in enumerate(results):
        if r == UNPLAYED:
            return i
    return None
