"""One joint score measure for every game market. No independent SGP products."""

from dataclasses import dataclass
from math import isfinite
from statistics import fmean, pvariance


class ModelHealthError(ValueError):
    pass


@dataclass(frozen=True)
class GameDistribution:
    samples: tuple[tuple[int, int], ...]

    def __post_init__(self):
        if len(self.samples) < 100:
            raise ModelHealthError("INSUFFICIENT_DISTRIBUTION_SUPPORT")
        if any(
            len(s) != 2 or any(not isfinite(x) or x < 0 or int(x) != x for x in s)
            for s in self.samples
        ):
            raise ModelHealthError("INVALID_SCORE_SUPPORT")

    def summary(self):
        h, a = zip(*self.samples)
        mh, ma = fmean(h), fmean(a)
        margin, total = [x - y for x, y in self.samples], [x + y for x, y in self.samples]
        cov = fmean((x - mh) * (y - ma) for x, y in self.samples)
        vh, va = pvariance(h), pvariance(a)

        def interval(values):
            values = sorted(values)
            return [values[int((len(values) - 1) * q)] for q in (0.05, 0.95)]

        return dict(
            expected_home_points=mh,
            expected_away_points=ma,
            expected_margin=fmean(margin),
            expected_total=fmean(total),
            margin_variance=pvariance(margin),
            total_variance=pvariance(total),
            home_variance=vh,
            away_variance=va,
            score_covariance=cov,
            score_correlation=cov / (vh * va) ** 0.5 if vh * va else None,
            margin_predictive_interval_90=interval(margin),
            total_predictive_interval_90=interval(total),
            sample_count=len(h),
            tie_probability=sum(x == y for x, y in self.samples) / len(h),
        )

    def outcome(self, market, selection, line, home, away, participant=None):
        from .score_distribution import outcome_probability

        if line is not None and not isfinite(float(line)):
            raise ModelHealthError("INVALID_THRESHOLD")
        p = outcome_probability(self.samples, market, selection, line, home, away, participant)
        if p is None:
            raise ModelHealthError("UNSUPPORTED_MARKET_IDENTITY")
        if any(not isfinite(v) or not -1e-12 <= v <= 1 + 1e-12 for v in p.values()):
            raise ModelHealthError("INVALID_PROBABILITY")
        if abs(sum(p.values()) - 1) > 1e-12:
            raise ModelHealthError("COMPLEMENT_FAILURE")
        return p

    def validate_ladders(self, home, away):
        # Full half-point ladder and integer pushes; evaluated before caching.
        previous = {home: 0.0, away: 0.0}
        for line in [x / 2 for x in range(-100, 101)]:
            for team, opponent in ((home, away), (away, home)):
                p = self.outcome("spreads", team, line, home, away)
                other = self.outcome("spreads", opponent, -line, home, away)
                if (
                    p["win"] + 1e-12 < previous[team]
                    or abs(p["win"] + other["win"] + p["push"] - 1) > 1e-12
                ):
                    raise ModelHealthError("SPREAD_LADDER_FAILURE")
                previous[team] = p["win"]
        previous = 1.0
        for line in [x / 2 for x in range(0, 201)]:
            p = self.outcome("totals", "Over", line, home, away)
            other = self.outcome("totals", "Under", line, home, away)
            if p["win"] > previous + 1e-12 or abs(p["win"] + other["win"] + p["push"] - 1) > 1e-12:
                raise ModelHealthError("TOTAL_LADDER_FAILURE")
            previous = p["win"]
        # Raw ML includes tie mass. Conditional-on-decisive ML is separately labeled.
        for team in (home, away):
            ml = self.outcome("h2h", team, None, home, away)
            zero = self.outcome("spreads", team, 0, home, away)
            if ml != zero:
                raise ModelHealthError("ML_SPREAD_FAILURE")
        return True

    def joint(self, legs, *, home, away, event_id):
        if not 2 <= len(legs) <= 4 or any(leg.get("event_id") != event_id for leg in legs):
            raise ModelHealthError("ALIGNED_SAME_EVENT_LEGS_REQUIRED")
        masks = []
        marginals = []
        for leg in legs:
            p = self.outcome(
                leg["market"], leg["selection"], leg.get("line"), home, away, leg.get("participant")
            )
            if p["push"]:
                raise ModelHealthError("SGP_PUSH_REPRICING_UNSUPPORTED")
            from .score_distribution import outcome_probability

            masks.append(
                [
                    outcome_probability(
                        [s],
                        leg["market"],
                        leg["selection"],
                        leg.get("line"),
                        home,
                        away,
                        leg.get("participant"),
                    )["win"]
                    == 1
                    for s in self.samples
                ]
            )
            marginals.append(p["win"])
        joint = sum(all(m[i] for m in masks) for i in range(len(self.samples))) / len(self.samples)
        return {
            "marginals": marginals,
            "joint_probability": joint,
            "method": "shared_score_scenarios",
            "sample_count": len(self.samples),
            "approved_for_betting": False,
            "priority": "protected_2_leg" if len(legs) == 2 else "selective",
        }
