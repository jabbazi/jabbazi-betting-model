"""Distributional NFL/MLB/NHL/NBA player-prop inference.

Artifacts are JSON, reproducible and fail closed.  A fitted mean is never treated as a
threshold hit probability; every supported market maps to an explicit distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import UTC, datetime
import math

from .base import ModelEstimate, ProbabilityModel
from .player_calibration import apply_calibration


NFL_PROP_MARKETS = frozenset({
    "player_pass_yds",
    "player_pass_attempts",
    "player_pass_completions",
    "player_pass_tds",
    "player_rush_yds",
    "player_rush_attempts",
    "player_receptions",
    "player_reception_yds",
    "player_anytime_td",
})
MLB_PROP_MARKETS = frozenset({
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_rbis",
    "batter_runs_scored",
    "batter_hits_runs_rbis",
    "batter_walks",
})
NHL_PROP_MARKETS = frozenset({
    "player_points",
    "player_power_play_points",
    "player_assists",
    "player_blocked_shots",
    "player_shots_on_goal",
    "player_goals",
    "player_total_saves",
})
NBA_PROP_MARKETS = frozenset({
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_blocks",
    "player_steals",
    "player_turnovers",
    "player_points_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_double_double",
})
PLAYER_PROP_MARKETS = {
    "americanfootball_nfl": NFL_PROP_MARKETS,
    "baseball_mlb": MLB_PROP_MARKETS,
    "icehockey_nhl": NHL_PROP_MARKETS,
    "basketball_nba": NBA_PROP_MARKETS,
}

BINARY_MARKETS = frozenset({"player_anytime_td", "batter_home_runs", "player_double_double"})
COUNT_MARKETS = frozenset({
    "player_pass_attempts",
    "player_pass_completions",
    "player_pass_tds",
    "player_rush_attempts",
    "player_receptions",
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "batter_hits",
    "batter_total_bases",
    "batter_rbis",
    "batter_runs_scored",
    "batter_hits_runs_rbis",
    "batter_walks",
    "player_points",
    "player_power_play_points",
    "player_assists",
    "player_blocked_shots",
    "player_shots_on_goal",
    "player_goals",
    "player_total_saves",
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_blocks",
    "player_steals",
    "player_turnovers",
    "player_points_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
})
CONTINUOUS_MARKETS = (
    NFL_PROP_MARKETS | MLB_PROP_MARKETS | NHL_PROP_MARKETS | NBA_PROP_MARKETS
) - BINARY_MARKETS - COUNT_MARKETS


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _poisson_cdf(k: int, mean: float) -> float:
    if k < 0:
        return 0.0
    if mean <= 0:
        return 1.0
    term = math.exp(-mean)
    total = term
    for i in range(1, k + 1):
        term *= mean / i
        total += term
    return min(1.0, total)


def _negative_binomial_cdf(k: int, mean: float, alpha: float) -> float:
    """NB2 CDF where variance = mean + alpha * mean^2."""
    if k < 0:
        return 0.0
    if mean <= 0:
        return 1.0
    if alpha <= 1e-8:
        return _poisson_cdf(k, mean)
    r = 1.0 / alpha
    success = r / (r + mean)
    # Stable recurrence: P(0)=p^r; P(x+1)=P(x)*(x+r)/(x+1)*(1-p)
    term = math.exp(r * math.log(success))
    total = term
    for x in range(k):
        term *= ((x + r) / (x + 1.0)) * (1.0 - success)
        total += term
    return min(1.0, max(0.0, total))


def _standardize(features: dict[str, float], artifact: dict) -> list[float]:
    names = artifact["feature_names"]
    means = artifact["scaler"]["mean"]
    scales = artifact["scaler"]["scale"]
    if not len(names) == len(means) == len(scales) or len(set(names)) != len(names):
        raise ValueError("Malformed player scaler")
    if set(features) != set(names):
        raise ValueError("Player feature schema mismatch")
    result = []
    for name, center, scale in zip(names, means, scales):
        value = float(features[name])
        if not all(math.isfinite(float(v)) for v in (value, center, scale)) or float(scale) <= 0:
            raise ValueError("Non-finite player feature")
        result.append((value - float(center)) / max(float(scale), 1e-12))
    return result


def _linear(vector: list[float], coefficients: list[float], intercept: float) -> float:
    if len(vector) != len(coefficients):
        raise ValueError("Coefficient/feature mismatch")
    return float(intercept) + sum(v * float(c) for v, c in zip(vector, coefficients))


def _isotonic(raw: float, calibration: dict | None) -> float:
    return apply_calibration(raw, calibration)


def distribution_mean(artifact: dict, features: dict[str, float]) -> tuple[float, float | None]:
    vector = _standardize(features, artifact)
    family = artifact["family"]
    params = artifact["parameters"]
    if family == "binary_logistic":
        return _sigmoid(_linear(vector, params["coef"], params["intercept"])), None
    if family == "count_nb":
        mean = math.exp(_linear(vector, params["coef"], params["intercept"]))
        return mean, float(params.get("dispersion", 0.0))
    if family == "normal_ridge":
        mean = _linear(vector, params["coef"], params["intercept"])
        return mean, None
    if family == "hurdle_lognormal":
        active = _sigmoid(_linear(vector, params["active_coef"], params["active_intercept"]))
        log_mean = _linear(vector, params["mean_coef"], params["mean_intercept"])
        sigma = max(1e-6, float(params["sigma"]))
        conditional_mean = max(0.0, math.exp(log_mean + sigma * sigma / 2.0) - 1.0)
        return active * conditional_mean, active
    raise ValueError("Unsupported player distribution family")


def raw_probability(artifact: dict, features: dict[str, float], side: str, line) -> float:
    side = side.lower()
    family = artifact["family"]
    vector = _standardize(features, artifact)
    params = artifact["parameters"]

    if family == "binary_logistic":
        if line is not None and float(line) != 0.5:
            raise ValueError("Binary prop only supports the anytime/0.5 threshold")
        yes = _sigmoid(_linear(vector, params["coef"], params["intercept"]))
        if side in {"yes", "over"}:
            return yes
        if side in {"no", "under"}:
            return 1.0 - yes
        raise ValueError("Binary prop side must be Yes/No")

    if line is None:
        raise ValueError("Threshold prop requires a line")
    threshold = float(line)
    if not math.isfinite(threshold):
        raise ValueError("Non-finite prop threshold")
    if family == "count_nb":
        mean = math.exp(_linear(vector, params["coef"], params["intercept"]))
        cdf = _negative_binomial_cdf(math.floor(threshold), mean, float(params.get("dispersion", 0)))
        over = 1.0 - cdf
    elif family == "normal_ridge":
        mean = _linear(vector, params["coef"], params["intercept"])
        sigma = max(1e-6, float(params["sigma"]))
        over = 1.0 - _normal_cdf((threshold - mean) / sigma)
    elif family == "hurdle_lognormal":
        active = _sigmoid(_linear(vector, params["active_coef"], params["active_intercept"]))
        if threshold < 0:
            over = 1.0
        elif threshold == 0:
            over = active
        else:
            log_mean = _linear(vector, params["mean_coef"], params["mean_intercept"])
            sigma = max(1e-6, float(params["sigma"]))
            z = (math.log1p(threshold) - log_mean) / sigma
            over = active * (1.0 - _normal_cdf(z))
    else:
        raise ValueError("Unsupported player distribution family")

    if side == "over":
        return min(1.0, max(0.0, over))
    if side == "under":
        if family == "count_nb":
            # Strictly below an integer threshold: equality is a push, not a win.
            return _negative_binomial_cdf(math.ceil(threshold) - 1, mean, float(params.get("dispersion", 0)))
        return min(1.0, max(0.0, 1.0 - over))
    raise ValueError("Threshold prop side must be Over/Under")


def calibrated_probability(artifact, features, side, line):
    """One calibrated positive tail; obtain its opposite by complementation.

The scanner's scalar EV contract has no push payout. Whole-number non-binary
lines stay unavailable until that contract explicitly accounts for settlements.
"""
    binary = artifact["market"] in BINARY_MARKETS
    if not binary and (line is None or not math.isfinite(float(line)) or float(line).is_integer()):
        raise ValueError("Push-capable player line requires settlement-aware pricing")
    side = side.lower()
    if side not in ({"yes", "no", "over", "under"} if binary else {"over", "under"}):
        raise ValueError("Unsupported player market side")
    positive = side in {"yes", "over"}
    calibration = artifact.get("calibration")
    if calibration and calibration.get("orientation") != "positive" and not positive:
        raise ValueError("Legacy calibrator has no verified negative-side mapping")
    raw = raw_probability(artifact, features, "yes" if binary else "over", line)
    p = apply_calibration(raw, calibration)
    return p if positive else 1 - p


@dataclass(frozen=True)
class PlayerPropModel(ProbabilityModel):
    artifact: dict
    store: object | None = None

    def __post_init__(self):
        sport = self.artifact.get("sport")
        market = self.artifact.get("market")
        if market not in PLAYER_PROP_MARKETS.get(sport, frozenset()):
            raise ValueError("Unsupported player-prop artifact")
        if self.artifact.get("artifact_type") != "player_prop_distribution":
            raise ValueError("Invalid player-prop artifact type")
        if self.artifact.get("family") not in {
            "binary_logistic", "count_nb", "normal_ridge", "hurdle_lognormal"
        }:
            raise ValueError("Invalid player-prop distribution family")
        if not self.artifact.get("model_version") or not self.artifact.get("feature_names"):
            raise ValueError("Incomplete player-prop artifact")
        object.__setattr__(self, "sport", sport)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "supported_markets", frozenset({market}))
        object.__setattr__(self, "stage", self.artifact.get("stage", "SHADOW_ONLY"))

    def _snapshot(self, price):
        if self.store is None or not price.participant:
            return None
        entity = f"{price.sport}|{price.event_id}|{price.participant}|{price.market}"
        records = self.store.list_records("player_feature_snapshot", 1, entity=entity)
        if not records:
            return None
        payload = records[0]["payload"]
        if payload.get("sport") != price.sport or payload.get("event_id") != price.event_id:
            return None
        if payload.get("participant") != price.participant or payload.get("market") != price.market:
            return None
        # Old provider snapshots lack authenticity evidence: quarantine them
        # without deleting or rewriting their immutable audit records.
        if "sportsdataio" in str(payload.get("provider", "")).lower() and payload.get("provider_data_verified") is not True:
            return None
        try:
            stamp = datetime.fromisoformat(payload["features_available_at"])
            start = datetime.fromisoformat(payload["starts_at"])
            now = datetime.now(UTC)
            if stamp.tzinfo is None or start.tzinfo is None:
                return None
            if stamp > now or stamp >= start or start <= now or (now-stamp).total_seconds() > 3600:
                return None
            if price.starts_at != start:
                return None
        except (ValueError, TypeError, KeyError):
            return None
        return payload

    def estimate(self, price):
        if (
            price.sport != self.sport
            or price.market != self.market
            or not price.participant
            or price.in_play
        ):
            return None
        snapshot = self._snapshot(price)
        if not snapshot:
            return None
        features = snapshot.get("features") or {}
        try:
            probability = raw_probability(
                self.artifact, features, price.selection, price.line
            )
            calibrated = calibrated_probability(self.artifact, features, price.selection, price.line)
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        validation = self.artifact.get("validation", {})
        required = (
            "event_identity", "player_identity", "fresh_features", "schema",
            "role", "availability", "injuries", "no_duplicate_event",
        )
        integrity = dict(snapshot.get("integrity", {}))
        # Reliability-layer fields shared with team models. Player distributions
        # have explicit variance by construction; role/player identity supply the
        # analogous starter/roster checks. Large model-market disagreements still
        # require an actual fitted calibrator before they can escape quarantine.
        integrity["variance"] = self.artifact["family"] in {
            "binary_logistic", "count_nb", "normal_ridge", "hurdle_lognormal"
        }
        integrity["starter"] = integrity.get("role") is True
        integrity["roster"] = integrity.get("player_identity") is True
        integrity["calibration"] = self.artifact.get("calibration") is not None
        integrity_ok = all(integrity.get(key) is True for key in required)
        approved = (
            self.stage == "PRODUCTION_APPROVED"
            and validation.get("promotion_passed") is True
            and integrity_ok
            and snapshot.get("research_only") is False
            and snapshot.get("production_inputs_verified") is True
        )
        n = int(validation.get("prospective_sample_count", 0) or 0)
        uncertainty = max(0.02, min(0.20, 1.96 * math.sqrt(max(calibrated * (1-calibrated), 1e-6) / max(n, 25))))
        mean, active = distribution_mean(self.artifact, features)
        feature_snapshot = {
            **snapshot,
            "integrity": integrity,
            "player_distribution": {
                "family": self.artifact["family"],
                "mean": mean,
                "active_probability": active,
                "raw_probability": probability,
                "calibrated_probability": calibrated,
                "market": self.market,
                "line": str(price.line) if price.line is not None else None,
                "side": price.selection,
            },
            "production_inputs_verified": approved,
        }
        return ModelEstimate(
            probability=Decimal(str(round(calibrated, 10))),
            uncertainty=Decimal(str(round(uncertainty, 10))),
            model_name=f"{self.sport}:{self.market}:player_distribution",
            model_version=self.artifact["model_version"],
            feature_snapshot=feature_snapshot,
            approved_for_betting=approved,
        )
