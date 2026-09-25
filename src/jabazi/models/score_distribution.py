"""Frozen score regressions + paired calibration residuals; shadow research only.

No inference dependency on sklearn/numpy. Paired score samples retain empirical
score dependence; they are not a fitted player-prop or same-game parlay model.
"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .base import ModelEstimate, ProbabilityModel
from .team_elo import SPORTS, timestamp

MARKETS = frozenset(
    {
        "h2h",
        "spreads",
        "alternate_spreads",
        "totals",
        "alternate_totals",
        "team_totals",
        "alternate_team_totals",
    }
)
FEATURES = (
    "home_scoring_form",
    "away_scoring_form",
    "home_conceding_form",
    "away_conceding_form",
    "rest_advantage_days",
    "home_field",
)


def available_at(row):
    return datetime.combine(
        timestamp(row["starts_at"]).date() + timedelta(days=2), datetime.min.time(), UTC
    )


def state_from_games(games, *, now, window):
    state = {}
    for row in sorted(games, key=lambda r: (timestamp(r["starts_at"]), str(r["game_id"]))):
        if available_at(row) >= now:
            continue
        for side, other in (("home", "away"), ("away", "home")):
            team = row[f"{side}_team"]
            state.setdefault(team, []).append(
                [
                    row[f"{side}_score"],
                    row[f"{other}_score"],
                    row["starts_at"],
                    available_at(row).isoformat(),
                    row[f"{other}_team"],
                ]
            )
            state[team] = state[team][-window:]
    return state


def features(state, home, away, start, neutral, minimum, policy=None):
    if policy is not None:
        from .form_features import recency_features
        return recency_features(state, home, away, start, neutral, minimum, policy)
    h, a = state.get(home, []), state.get(away, [])
    if len(h) < minimum or len(a) < minimum or type(neutral) is not bool:
        return None
    if any(timestamp(g[3]) >= start for g in h + a):
        return None
    mean = lambda rows, col: sum(float(r[col]) for r in rows) / len(rows)
    rest = lambda rows: min(21, max(0, (start - timestamp(rows[-1][2])).total_seconds() / 86400))
    return [mean(h, 0), mean(a, 0), mean(h, 1), mean(a, 1), rest(h) - rest(a), float(not neutral)]


def score_samples(artifact, vector):
    x = [(v - m) / s for v, m, s in zip(vector, artifact["mean"], artifact["scale"], strict=True)]
    means = [
        b + sum(c * v for c, v in zip(coef, x, strict=True))
        for b, coef in zip(artifact["intercepts"], artifact["coefficients"], strict=True)
    ]
    return [
        (max(0, math.floor(means[0] + h + 0.5)), max(0, math.floor(means[1] + a + 0.5)))
        for h, a in artifact["residual_pairs"]
    ]


def outcome_probability(samples, market, selection, line, home, away, participant=None):
    """Return win/push/loss explicitly. Never price an integer push as a loss."""
    if market not in MARKETS or not samples:
        return None
    if market == "h2h":
        if selection not in (home, away):
            return None
        outcomes = [h - a if selection == home else a - h for h, a in samples]
    elif market in {"spreads", "alternate_spreads"}:
        if selection not in (home, away) or line is None:
            return None
        outcomes = [(h - a if selection == home else a - h) + float(line) for h, a in samples]
    else:
        if selection.lower() not in {"over", "under"} or line is None:
            return None
        if market in {"team_totals", "alternate_team_totals"} and participant not in (home, away):
            return None
        values = [
            h if participant == home else a if participant == away else h + a for h, a in samples
        ]
        outcomes = [(v - float(line)) * (1 if selection.lower() == "over" else -1) for v in values]
    n = len(outcomes)
    win, push = sum(v > 0 for v in outcomes) / n, sum(v == 0 for v in outcomes) / n
    return {"win": win, "push": push, "loss": 1 - win - push}


class ScoreDistributionModel(ProbabilityModel):
    supported_markets = MARKETS

    def __init__(self, artifact):
        self.artifact = artifact
        self.sport = artifact["sport"]
        if artifact.get("schema_version") != 1 or self.sport not in SPORTS.values():
            raise ValueError("Invalid score artifact")
        if (
            artifact.get("features") != list(FEATURES)
            or len(artifact["mean"]) != 6
            or len(artifact["scale"]) != 6
        ):
            raise ValueError("Feature schema mismatch")
        if len(artifact["coefficients"]) != 2 or any(len(c) != 6 for c in artifact["coefficients"]):
            raise ValueError("Invalid coefficients")
        if len(artifact["intercepts"]) != 2 or len(artifact["residual_pairs"]) < 100:
            raise ValueError("Insufficient fitted evidence")
        numbers = (
            artifact["mean"]
            + artifact["scale"]
            + artifact["intercepts"]
            + [v for row in artifact["coefficients"] for v in row]
        )
        if any(not math.isfinite(v) for v in numbers) or any(s <= 0 for s in artifact["scale"]):
            raise ValueError("Invalid numerical parameters")
        if any(
            len(pair) != 2 or any(not math.isfinite(v) for v in pair)
            for pair in artifact["residual_pairs"]
        ):
            raise ValueError("Invalid residuals")
        if not artifact.get("model_version") or not artifact.get("source_checksum"):
            raise ValueError("Missing provenance")
        timestamp(artifact["state_refreshed_at"])
        timestamp(artifact["trained_at"])
        self._cache = {}

    def estimate(self, price):
        if price.sport != self.sport or price.market not in MARKETS or " @ " not in price.event:
            return None
        if price.in_play or price.starts_at is None or price.starts_at <= price.observed_at:
            return None
        refreshed = timestamp(self.artifact["state_refreshed_at"])
        if not 0 <= (price.observed_at - refreshed).total_seconds() <= 36 * 3600:
            return None
        if price.observed_at < timestamp(self.artifact["trained_at"]):
            return None
        from jabazi.providers.history import MLB_ALIASES

        aliases = MLB_ALIASES if self.sport == SPORTS["mlb"] else self.artifact.get("team_aliases", {})
        away, home = [aliases.get(t.strip(), t.strip()) for t in price.event.split(" @ ", 1)]
        # Match explicit schedule evidence; do not infer neutral-site status from book ordering.
        events = [
            e
            for e in self.artifact.get("events", [])
            if e["home_team"] == home
            and e["away_team"] == away
            and abs((timestamp(e["starts_at"]) - price.starts_at).total_seconds()) <= 60
        ]
        if len(events) != 1 or type(events[0].get("neutral_site")) is not bool:
            return None
        event = events[0]
        if event.get("provider_event_id") and event["provider_event_id"] != price.event_id:
            return None
        if event.get("season") is not None and event["season"] not in (price.starts_at.year, price.starts_at.year-1):
            return None
        if event.get("week") is not None and not 0 <= event["week"] <= 30:
            return None
        for team in (home, away):
            games = self.artifact["team_state"].get(team, [])
            max_age = 21 if self.sport == SPORTS["nfl"] else 7
            if (
                not games
                or (price.observed_at - timestamp(games[-1][2])).total_seconds() > max_age * 86400
            ):
                return None
        key = (home, away, price.starts_at.isoformat(), event["neutral_site"])
        if key not in self._cache:
            vector = features(
                self.artifact["team_state"],
                home,
                away,
                price.starts_at,
                event["neutral_site"],
                self.artifact["minimum_games"],
                self.artifact.get("feature_policy"),
            )
            if vector is None:
                return None
            # Features must have been available at observation time, not just at kickoff.
            if any(
                timestamp(g[3]) >= price.observed_at
                for t in (home, away)
                for g in self.artifact["team_state"][t]
            ):
                return None
            from .game_distribution import GameDistribution
            distribution = GameDistribution(tuple(score_samples(self.artifact, vector)))
            distribution.validate_ladders(home, away)
            self._cache[key] = (vector, distribution)
        vector, distribution = self._cache[key]
        samples = distribution.samples
        selection = aliases.get(price.selection, price.selection)
        participant = aliases.get(price.participant, price.participant)
        result = outcome_probability(
            samples, price.market, selection, price.line, home, away, participant
        )
        if result is None:
            return None
        # Existing binary scanner EV cannot account for pushes. Half-point lines
        # work; integer lines remain unavailable until settlement-aware integration.
        if price.market != "h2h" and result["push"] > 0:
            return None
        if price.market == "h2h":
            decisive = result["win"] + result["loss"]
            if decisive <= 0:
                return None
            p = result["win"] / decisive
        else:
            p = result["win"]
        if not 0 < p < 1:
            return None
        import hashlib
        import json
        scaled = [(x-m)/scale for x,m,scale in zip(vector, self.artifact["mean"], self.artifact["scale"], strict=True)]
        summary = distribution.summary()
        history = {team: self.artifact["team_state"][team] for team in (home, away)}
        snapshot_id = hashlib.sha256(json.dumps([self.artifact["model_version"], key, vector, history], sort_keys=True).encode()).hexdigest()
        return ModelEstimate(
            Decimal(str(p)),
            Decimal("0.08"),
            self.artifact["model_name"],
            self.artifact["model_version"],
            {
                "features": dict(zip(FEATURES, vector, strict=True)),
                "scaled_features": dict(zip(FEATURES, scaled, strict=True)),
                "feature_schema_version": self.artifact.get("feature_schema_version", "score-form-v1"),
                "snapshot_id": snapshot_id,
                "training_data_cutoff": self.artifact.get("training_data_cutoff"),
                "dataset_hash": self.artifact["source_checksum"],
                "calibration_version": self.artifact.get("calibration_version"),
                "code_commit": __import__("os").getenv("RENDER_GIT_COMMIT"),
                "model_artifact_hash": hashlib.sha256(json.dumps(self.artifact,sort_keys=True).encode()).hexdigest(),
                "team_history": history,
                "home_team": home, "away_team": away,
                "provider_event_id": price.event_id,
                "canonical_selection": selection, "canonical_participant": participant,
                "game_distribution": summary,
                "raw_win_probability": result["win"],
                "loss_probability": result["loss"],
                "integrity": {
                    "event_identity": event.get("provider_event_id") == price.event_id,
                    "schedule_identity": True,
                    "line_identity": True, "fresh_features": True,
                    "schema": True,
                    "variance": summary["margin_variance"] > 0 and summary["total_variance"] > 0,
                    "no_duplicate_event": True,
                    "starter": False, "roster": False, "injuries": False,
                    "calibration": False,
                    "feature_drift": any(abs(z) > 6 for z in scaled[:-1]),
                },
                "source_checksum": self.artifact["source_checksum"],
                "state_source_checksum": self.artifact.get("state_source_checksum"),
                "state_refreshed_at": self.artifact["state_refreshed_at"],
                "schedule_game_id": event["game_id"],
                "score_sample_count": len(samples),
                "push_probability": result["push"],
                "conditional_on_no_tie": price.market == "h2h",
                "production_inputs_verified": False,
                "limitations": self.artifact["limitations"],
            },
            approved_for_betting=False,
        )
