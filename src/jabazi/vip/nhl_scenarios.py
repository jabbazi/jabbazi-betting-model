"""Exact NHL scenario probabilities from the gated canonical model snapshot.

These are weighted outcomes, not Monte Carlo draws or bookmaker settlement approval.
"""
from ..models.nhl_goals import score_grid, probability


class NHLScenarios:
    def __init__(self, snapshot):
        self.grid = score_grid(*snapshot["regulation_goal_rates"],
                               snapshot["overtime_home_probability"])

    def outcome(self, market, selection, line, home, away):
        return probability(self.grid, market, selection, line, home, away)

    def summary(self):
        def interval(transform):
            mass = {}
            for (h, a), p in self.grid.items():
                value = transform(h, a)
                mass[value] = mass.get(value, 0) + p
            def quantile(q):
                cumulative = 0
                for value, p in sorted(mass.items()):
                    cumulative += p
                    if cumulative >= q:
                        return value
                return max(mass)
            return [quantile(.05), quantile(.95)]
        home = sum(h*p for (h, a), p in self.grid.items())
        away = sum(a*p for (h, a), p in self.grid.items())
        return {"expected_home_points": home, "expected_away_points": away,
                "expected_total": home+away, "expected_margin": home-away,
                "sample_count": len(self.grid), "count_label": "Weighted score outcomes",
                "margin_predictive_interval_90": interval(lambda h, a: h-a),
                "total_predictive_interval_90": interval(lambda h, a: h+a)}
