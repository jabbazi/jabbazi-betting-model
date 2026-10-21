"""Recency/shrinkage challenger: score-form evidence, not invented EPA or personnel."""

from math import exp, log
from .team_elo import timestamp

POLICIES = {
    "nfl": {"half_life_days": 90.0, "prior_games": 3.0, "opponent_adjustment": 0.5},
    "cfb": {"half_life_days": 60.0, "prior_games": 4.0, "opponent_adjustment": 0.5},
    "mlb": {"half_life_days": 30.0, "prior_games": 8.0, "opponent_adjustment": 0.25},
}


def recency_features(state, home, away, start, neutral, minimum, policy):
    h, a = state.get(home, []), state.get(away, [])
    if min(len(h), len(a)) < minimum or type(neutral) is not bool:
        return None
    if any(timestamp(g[3]) >= start for games in state.values() for g in games):
        raise ValueError("Feature state includes future labels")
    half = float(policy["half_life_days"])
    prior = float(policy["prior_games"])
    if half <= 0 or prior < 0:
        raise ValueError("Invalid recency prior")

    def weight(g):
        return exp(-log(2) * max(0, (start - timestamp(g[2])).total_seconds() / 86400) / half)

    population = [g for games in state.values() for g in games]
    mass = sum(weight(g) for g in population)
    if not mass:
        return None
    league = sum(weight(g) * g[0] for g in population) / mass

    def form(team, col):
        games = state.get(team, [])
        return (prior * league + sum(weight(g) * g[col] for g in games)) / (
            prior + sum(weight(g) for g in games)
        )

    def adjusted(games, col):
        value = prior * league
        for g in games:
            opponent = g[4] if len(g) > 4 else None
            correction = league - form(opponent, 1 - col) if opponent in state else 0.0
            value += weight(g) * (g[col] + float(policy["opponent_adjustment"]) * correction)
        return value / (prior + sum(weight(g) for g in games))

    rest = lambda games: min(21, max(0, (start - timestamp(games[-1][2])).total_seconds() / 86400))
    return [
        adjusted(h, 0),
        adjusted(a, 0),
        adjusted(h, 1),
        adjusted(a, 1),
        rest(h) - rest(a),
        float(not neutral),
    ]
