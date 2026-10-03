"""Coherent NHL regulation-goals distribution with explicit OT/SO resolution.

Runtime uses only the standard library. All market outcomes share one score grid.
The first model deliberately has no player/goalie projections or betting approval.
"""

import hashlib
import json
import math
import os
from decimal import Decimal

from jabazi.models.base import ModelEstimate, ProbabilityModel
from jabazi.models.score_distribution import MARKETS
from jabazi.models.team_elo import timestamp
from jabazi.providers.nhl import SPORT, SCHEMA, canonical

FEATURES = (
    "log_own_goals_for",
    "log_opponent_goals_against",
    "home_ice",
    "rest_days",
    "opponent_rest_days",
)
SETTLEMENT = "full_game_including_ot_one_shootout_deciding_goal"


def poisson(rate):
    if not math.isfinite(rate) or not 0 < rate <= 12:
        raise ValueError("NHL goal rate outside supported range")
    mass = [math.exp(-rate)]
    while 1 - sum(mass) > 1e-13:
        mass.append(mass[-1] * rate / len(mass))
        if len(mass) > 100:
            raise ValueError("NHL distribution failed to converge")
    total = sum(mass)
    return [p / total for p in mass]


def score_grid(home_rate, away_rate, overtime_home_probability):
    if not math.isfinite(overtime_home_probability) or not 0 < overtime_home_probability < 1:
        raise ValueError("Invalid overtime model")
    result = {}
    for h, hp in enumerate(poisson(home_rate)):
        for a, ap in enumerate(poisson(away_rate)):
            p = hp * ap
            if h == a:
                result[h + 1, a] = result.get((h + 1, a), 0) + p * overtime_home_probability
                result[h, a + 1] = result.get((h, a + 1), 0) + p * (1 - overtime_home_probability)
            else:
                result[h, a] = result.get((h, a), 0) + p
    if abs(sum(result.values()) - 1) > 1e-10 or any(h == a for h, a in result):
        raise ValueError("NHL final-score coherence failure")
    return result


def probability(grid, market, selection, line, home, away, participant=None):
    if market not in MARKETS:
        return None
    if market != "h2h" and (line is None or not math.isfinite(float(line))):
        return None
    if market in {"h2h", "spreads", "alternate_spreads"} and selection not in {home, away}:
        return None
    if "totals" in market and selection.lower() not in {"over", "under"}:
        return None
    if "team_totals" in market and participant not in {home, away}:
        return None
    answer = {"win": 0.0, "push": 0.0, "loss": 0.0}
    for (h, a), mass in grid.items():
        if market == "h2h":
            value = (h - a) * (1 if selection == home else -1)
        elif market in {"spreads", "alternate_spreads"}:
            value = (h - a) * (1 if selection == home else -1) + float(line)
        else:
            score = (h if participant == home else a) if "team_totals" in market else h + a
            value = (score - float(line)) * (1 if selection.lower() == "over" else -1)
        answer["win" if value > 0 else "loss" if value < 0 else "push"] += mass
    return answer


def team_state(games, as_of):
    state = {}
    for row in games:
        if not row["completed"] or timestamp(row["available_at"]) >= as_of:
            continue
        for side, other in (("home", "away"), ("away", "home")):
            entry = [
                row[f"regulation_{side}"],
                row[f"regulation_{other}"],
                row["starts_at"],
                row["available_at"],
                row["game_id"],
            ]
            state.setdefault(row[f"{side}_team"], []).append(entry)
    return {t: sorted(v, key=lambda r: (r[2], r[4]))[-100:] for t, v in state.items()}


def form(history, as_of, league_rate):
    # Decays across the offseason instead of treating last season as current form.
    past = [
        r
        for r in history
        if timestamp(r[3]) < as_of and 0 < (as_of - timestamp(r[2])).total_seconds() <= 365 * 86400
    ]
    if not past:
        return None
    weights = [2 ** (-(as_of - timestamp(r[2])).total_seconds() / (90 * 86400)) for r in past]
    n = sum(weights)
    scored = (10 * league_rate + sum(w * r[0] for w, r in zip(weights, past))) / (10 + n)
    allowed = (10 * league_rate + sum(w * r[1] for w, r in zip(weights, past))) / (10 + n)
    rest = min(7, (as_of - max(timestamp(r[2]) for r in past)).total_seconds() / 86400)
    return scored, allowed, rest, n


def feature_pair(state, event, as_of, league_rate):
    h = form(state.get(event["home_team"], []), as_of, league_rate)
    a = form(state.get(event["away_team"], []), as_of, league_rate)
    if h is None or a is None:
        return None
    return (
        [math.log(h[0]), math.log(a[1]), int(not event["neutral_site"]), h[2], a[2]],
        [math.log(a[0]), math.log(h[1]), 0, a[2], h[2]],
    )


def rates(artifact, vectors, *, calibrated=True):
    factor = artifact["goal_rate_calibration"] if calibrated else 1.0
    values = [
        factor
        * math.exp(
            artifact["intercept"]
            + sum(c * x for c, x in zip(artifact["coefficients"], v, strict=True))
        )
        for v in vectors
    ]
    if any(not math.isfinite(x) or not 0 < x <= 12 for x in values):
        raise ValueError("NHL predicted rate invalid")
    return values


class NHLGoalsModel(ProbabilityModel):
    sport = SPORT
    supported_markets = MARKETS
    # Promotion requires a new reviewed release with goalie/settlement context.
    stage = "SHADOW_ONLY"

    def __init__(self, artifact):
        self.artifact = artifact
        if (
            artifact.get("sport") != SPORT
            or artifact.get("feature_schema_version") != SCHEMA
            or artifact.get("settlement") != SETTLEMENT
            or artifact.get("schema_version") != 1
            or artifact.get("status") == "UNAVAILABLE"
        ):
            raise ValueError("Invalid NHL artifact identity")
        coefficients = artifact["coefficients"]
        numbers = [
            *coefficients,
            artifact["intercept"],
            artifact["league_rate"],
            artifact["goal_rate_calibration"],
            artifact["overtime_home_probability"],
        ]
        if len(coefficients) != len(FEATURES) or any(not math.isfinite(v) for v in numbers):
            raise ValueError("Invalid NHL coefficients")
        if not (
            0 < artifact["goal_rate_calibration"] < 3
            and 0 < artifact["league_rate"] < 12
            and 0 < artifact["overtime_home_probability"] < 1
        ):
            raise ValueError("Invalid NHL calibration")
        for field in ("training_feature_mean", "training_feature_std"):
            if len(artifact[field]) != len(FEATURES) or any(
                not math.isfinite(x) for x in artifact[field]
            ):
                raise ValueError("Invalid NHL feature schema")
        if len(artifact["feature_ranges"]) != len(FEATURES) or any(
            len(pair) != 2 or not all(math.isfinite(x) for x in pair) or pair[0] >= pair[1]
            for pair in artifact["feature_ranges"]
        ):
            raise ValueError("Invalid NHL feature ranges")
        timestamp(artifact["training_data_cutoff"])
        timestamp(artifact["trained_at"])
        timestamp(artifact["state_refreshed_at"])
        ids = set()
        for event in artifact["events"]:
            if event["game_id"] in ids or event["home_team"] == event["away_team"]:
                raise ValueError("Duplicate NHL event")
            ids.add(event["game_id"])
        for history in artifact["team_state"].values():
            game_ids = set()
            for r in history:
                if len(r) != 5 or r[4] in game_ids or timestamp(r[2]) >= timestamp(r[3]):
                    raise ValueError("Invalid NHL feature history")
                if any(type(n) is not int or not 0 <= n <= 25 for n in r[:2]):
                    raise ValueError("Invalid NHL historical goals")
                game_ids.add(r[4])
        self._cache = {}

    def estimate(self, price):
        now = price.observed_at
        refreshed = timestamp(self.artifact["state_refreshed_at"])
        if (
            price.sport != SPORT
            or price.market not in self.supported_markets
            or price.in_play
            or price.stale
            or not price.starts_at
            or price.starts_at <= now
            or not 0 <= (now - refreshed).total_seconds() <= 36 * 3600
            or timestamp(self.artifact["trained_at"]) > now
            or not 0 <= (now - price.source_timestamp).total_seconds() <= 120
        ):
            return None
        parts = price.event.split(" @ ")
        if len(parts) != 2:
            return None
        away, home = map(canonical, parts)
        matches = [
            e
            for e in self.artifact["events"]
            if e["home_team"] == home
            and e["away_team"] == away
            and abs((timestamp(e["starts_at"]) - price.starts_at).total_seconds()) <= 60
        ]
        if len(matches) != 1:
            return None
        event = matches[0]
        if (
            event.get("provider_event_id") not in {None, price.event_id}
            or event.get("game_type") != 2
            or event.get("completed")
            or not event.get("scheduled")
            or event["season"] != self.artifact["active_season"]
        ):
            return None
        # Do not convert a three-outcome/push market to binary expected value.
        if price.market != "h2h" and (price.line is None or price.line % 1 == 0):
            return None
        vectors = feature_pair(
            self.artifact["team_state"], event, now, self.artifact["league_rate"]
        )
        if vectors is None:
            return None
        for vector in vectors:
            if any(
                x < lo - 1e-6 or x > hi + 1e-6
                for x, (lo, hi) in zip(vector, self.artifact["feature_ranges"], strict=True)
            ):
                return None
        key = (event["game_id"], tuple(tuple(v) for v in vectors))
        if key not in self._cache:
            h, a = rates(self.artifact, vectors)
            self._cache[key] = score_grid(h, a, self.artifact["overtime_home_probability"])
            if len(self._cache) > 200:
                self._cache.pop(next(iter(self._cache)))
        grid = self._cache[key]
        selection = canonical(price.selection)
        participant = canonical(price.participant) if price.participant else None
        result = probability(grid, price.market, selection, price.line, home, away, participant)
        if result is None or result["push"] > 1e-12:
            return None
        uncal_grid = score_grid(
            *rates(self.artifact, vectors, calibrated=False),
            self.artifact["overtime_home_probability"],
        )
        uncal = probability(
            uncal_grid, price.market, selection, price.line, home, away, participant
        )
        expected_home = sum(h * p for (h, a), p in grid.items())
        expected_away = sum(a * p for (h, a), p in grid.items())
        summary = {
            "expected_home_goals": expected_home,
            "expected_away_goals": expected_away,
            "expected_margin": expected_home - expected_away,
            "expected_total": expected_home + expected_away,
            "margin_variance": sum(
                (h - a - expected_home + expected_away) ** 2 * p for (h, a), p in grid.items()
            ),
            "total_variance": sum(
                (h + a - expected_home - expected_away) ** 2 * p for (h, a), p in grid.items()
            ),
        }
        snapshot = {
            "home_team": home,
            "away_team": away,
            "canonical_selection": selection,
            "canonical_participant": participant,
            "schedule_game_id": event["game_id"],
            "feature_schema_version": SCHEMA,
            "features": {
                "home": dict(zip(FEATURES, vectors[0])),
                "away": dict(zip(FEATURES, vectors[1])),
            },
            "dataset_hash": self.artifact["source_checksum"],
            "code_commit": os.getenv("RENDER_GIT_COMMIT"),
            "training_data_cutoff": self.artifact["training_data_cutoff"],
            "state_refreshed_at": self.artifact["state_refreshed_at"],
            "state_source_checksum": self.artifact.get("state_source_checksum"),
            "calibration_version": self.artifact["calibration_version"],
            "raw_model_probability": uncal["win"],
            "calibrated_model_probability": result["win"],
            "push_probability": result["push"],
            "loss_probability": result["loss"],
            "settlement": SETTLEMENT,
            "settlement_verified_for_book": False,
            "regulation_goal_rates": rates(self.artifact, vectors),
            "game_distribution": summary,
            "team_history": {t: self.artifact["team_state"][t] for t in (home, away)},
            "overtime_home_probability": self.artifact["overtime_home_probability"],
            "production_inputs_verified": False,
            "integrity": {
                "event_identity": bool(event.get("provider_event_id") == price.event_id),
                "schedule_identity": True,
                "line_identity": True,
                "fresh_features": True,
                "schema": True,
                "variance": True,
                "no_duplicate_event": True,
                "starter": False,
                "roster": False,
                "injuries": False,
                "calibration": False,
                "feature_drift": any(
                    abs((x - m) / sd) > 6
                    for v in vectors
                    for x, m, sd in zip(
                        v,
                        self.artifact["training_feature_mean"],
                        self.artifact["training_feature_std"],
                        strict=True,
                    )
                    if sd > 1e-8
                ),
            },
            "limitations": self.artifact["limitations"],
        }
        snapshot["snapshot_id"] = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode()
        ).hexdigest()
        return ModelEstimate(
            Decimal(str(result["win"])),
            Decimal("0.08"),
            self.artifact["model_name"],
            self.artifact["model_version"],
            snapshot,
            approved_for_betting=False,
        )
