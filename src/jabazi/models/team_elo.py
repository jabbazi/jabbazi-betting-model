"""Three independently trained, shadow-only pregame moneyline baselines.

Hyperparameters are selected on the penultimate season; the final holdout is
never used for tuning. Historical result updates wait until two UTC date
boundaries after their start (a conservative 24–48 hour delay). Suspended MLB
games are excluded by the adapter. Exact completion times remain a data upgrade.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .base import ModelEstimate, ProbabilityModel

SPORTS = {"mlb": "baseball_mlb", "nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}
GRIDS = {
    "mlb": ((8, 16, 24), (16, 24, 32), (0.65, 0.85)),
    "nfl": ((16, 24, 32), (35, 50, 65), (0.50, 0.75)),
    "cfb": ((20, 32, 44), (35, 55, 75), (0.45, 0.70)),
}


def probability(home, away, advantage):
    exponent = max(-12.0, min(12.0, -(home + advantage - away) / 400.0))
    return 1 / (1 + 10**exponent)


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("History timestamps must have a timezone")
    return dt.astimezone(UTC)


def metrics(pairs):
    if not pairs:
        return {"n": 0, "brier": None, "log_loss": None}
    return {
        "n": len(pairs),
        "brier": sum((p - y) ** 2 for p, y in pairs) / len(pairs),
        "log_loss": -sum(
            y * math.log(max(p, 1e-12)) + (1 - y) * math.log(max(1 - p, 1e-12)) for p, y in pairs
        )
        / len(pairs),
    }


def market_probability(row):
    values = (row.get("home_moneyline"), row.get("away_moneyline"))
    if any(v is None for v in values):
        return None
    h, a = map(float, values)
    if not all(math.isfinite(v) and abs(v) >= 100 for v in (h, a)):
        return None

    def implied(v):
        return -v / (100 - v) if v < 0 else 100 / (100 + v)

    return implied(h) / (implied(h) + implied(a))


def validate_history(payload, sport):
    if payload.get("sport") != SPORTS[sport]:
        raise ValueError("History sport does not match requested model")
    rows = payload.get("games", [])
    if not rows:
        raise ValueError("No completed games supplied")
    seen = set()
    for row in rows:
        key = str(row["game_id"])
        if key in seen:
            raise ValueError("Duplicate game_id in history")
        seen.add(key)
        if row["home_team"] == row["away_team"] or not all(
            isinstance(row[k], str) and row[k].strip() for k in ("home_team", "away_team")
        ):
            raise ValueError("Invalid team identities")
        timestamp(row["starts_at"])
        for side in ("home_score", "away_score"):
            if type(row[side]) is not int or row[side] < 0:
                raise ValueError(
                    "Only completed games with nonnegative integer scores are accepted"
                )
        if type(row.get("neutral_site")) is not bool:
            raise ValueError("neutral_site must be an explicit boolean")
        if type(row["season"]) is not int:
            raise ValueError("season must be an integer")
    return sorted(rows, key=lambda g: (timestamp(g["starts_at"]), str(g["game_id"])))


def replay(rows, k, advantage, retention):
    ratings, predictions = {}, []
    current_season = None
    pending = []
    for day, group in itertools.groupby(rows, key=lambda g: timestamp(g["starts_at"]).date()):
        games = list(group)
        ready = [item for item in pending if item[0] <= day]
        pending = [item for item in pending if item[0] > day]
        for _, changes in ready:
            for team, delta in changes.items():
                ratings[team] += delta
        seasons = {g["season"] for g in games}
        if len(seasons) != 1:
            raise ValueError("Mixed seasons on one UTC date")
        season = games[0]["season"]
        if current_season is not None and season != current_season:
            if season < current_season:
                raise ValueError("Season ordering is inconsistent with game dates")
            ratings = {
                t: 1500 + (r - 1500) * retention ** (season - current_season)
                for t, r in ratings.items()
            }
        current_season = season
        changes = defaultdict(float)
        for g in games:
            h, a = g["home_team"], g["away_team"]
            ratings.setdefault(h, 1500.0)
            ratings.setdefault(a, 1500.0)
            p = probability(ratings[h], ratings[a], 0 if g["neutral_site"] else advantage)
            y = (
                0.5
                if g["home_score"] == g["away_score"]
                else float(g["home_score"] > g["away_score"])
            )
            predictions.append((g, p, y))
            delta = k * (y - p)
            changes[h] += delta
            changes[a] -= delta
        pending.append((day + timedelta(days=2), changes))
    # All supplied results are completed at download time. Flush for future
    # inference only, after every historical prediction has been recorded.
    for _, changes in pending:
        for team, delta in changes.items():
            ratings[team] += delta
    return ratings, predictions


def train(source, destination, sport, holdout_season):
    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    rows = validate_history(payload, sport)
    # Post-holdout rows update the deployable ratings only, never tune or evaluate.
    seasons = sorted({g["season"] for g in rows if g["season"] <= holdout_season})
    if len(seasons) < 3 or seasons[-1] != holdout_season:
        raise ValueError("Need training, tuning, and explicit holdout seasons")
    tuning = seasons[-2]
    tune_rows = [g for g in rows if g["season"] <= tuning]
    candidates = []
    for k, advantage, retention in itertools.product(*GRIDS[sport]):
        _, preds = replay(tune_rows, k, advantage, retention)
        score = metrics([(p, y) for g, p, y in preds if g["season"] == tuning and y != 0.5])
        if score["n"]:
            candidates.append((score["log_loss"], k, advantage, retention))
    if not candidates:
        raise ValueError("Tuning season has no decisive games")
    tune_loss, k, advantage, retention = min(candidates)
    ratings, preds = replay(rows, k, advantage, retention)
    holdout = [(g, p, y) for g, p, y in preds if g["season"] == holdout_season and y != 0.5]
    if not holdout:
        raise ValueError("Holdout season has no decisive games")
    paired, timed = [], []
    for g, p, y in holdout:
        market = market_probability(g)
        if market is None:
            continue
        paired.append((p, market, y))
        observed = g.get("odds_observed_at")
        if observed and timestamp(observed) < timestamp(g["starts_at"]):
            timed.append((p, market, y))

    def comparison(values):
        return {
            "model": metrics([(p, y) for p, m, y in values]),
            "market": metrics([(m, y) for p, m, y in values]),
        }

    next_day = timestamp(rows[-1]["starts_at"]).date() + timedelta(days=1)
    trained_at = datetime.now(UTC)
    artifact = {
        "schema_version": 1,
        "model_name": f"{sport}_moneyline_elo_baseline",
        "model_version": "0.2.0",
        "sport": SPORTS[sport],
        "status": "SHADOW_ONLY",
        "approved_for_betting": False,
        "trained_at": trained_at.isoformat(),
        "ratings_effective_at": max(
            trained_at, datetime.combine(next_day, datetime.min.time(), UTC)
        ).isoformat(),
        "history_through_date": next_day.isoformat(),
        "last_season": rows[-1]["season"],
        "source_checksum": hashlib.sha256(raw).hexdigest(),
        "provider": payload.get("provider"),
        "history_games": len(rows),
        "training_seasons": seasons[:-2],
        "tuning_season": tuning,
        "holdout_season": holdout_season,
        "tuning_log_loss": tune_loss,
        "parameters": {"k": k, "home_advantage": advantage, "season_retention": retention},
        "holdout": metrics([(p, y) for g, p, y in holdout]),
        "paired_market_diagnostic": comparison(paired),
        "timestamp_verified_market_comparison": comparison(timed),
        "holdout_ties_excluded": sum(
            g["season"] == holdout_season and y == 0.5 for g, p, y in preds
        ),
        "uncertainty": 0.05,
        "validation_reasons": [
            "Research baseline; no production authorization or prospective paper-trading evidence",
            "Timestamped historical odds, calibration review, and sport-specific features still required",
            "No spreads, totals, props, parlays, or live betting support",
        ],
        "team_ratings": dict(sorted(ratings.items())),
    }
    out = Path(destination)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    return artifact


class TeamEloModel(ProbabilityModel):
    supported_markets = frozenset({"h2h"})

    def __init__(self, path, aliases=None, events=None):
        self.artifact = json.loads(Path(path).read_text())
        if (
            self.artifact.get("schema_version") != 1
            or self.artifact.get("sport") not in SPORTS.values()
        ):
            raise ValueError("Unsupported model artifact")
        self.sport = self.artifact["sport"]
        from jabazi.providers.history import MLB_ALIASES

        self.aliases = {**(MLB_ALIASES if self.sport == "baseball_mlb" else {}), **(aliases or {})}
        self.events = events or {}

    def estimate(self, price):
        if price.sport != self.sport or price.market != "h2h" or " @ " not in price.event:
            return None
        if price.starts_at is None or price.starts_at < timestamp(
            self.artifact["ratings_effective_at"]
        ):
            return None
        # Refuse to score with obsolete results (five days is a research limit,
        # not a guarantee of current rosters or injuries).
        coverage = timestamp(self.artifact["history_through_date"] + "T00:00:00+00:00")
        age = (price.observed_at - coverage).total_seconds()
        if age > 5 * 86400 or price.observed_at < timestamp(self.artifact["ratings_effective_at"]):
            return None
        a, h = [self.aliases.get(t.strip(), t.strip()) for t in price.event.split(" @ ", 1)]
        ratings = self.artifact["team_ratings"]
        if h not in ratings or a not in ratings:
            return None
        context = self.events.get(price.event_id, {})
        neutral = context.get("neutral_site")
        # Football venue status cannot be safely inferred from home/away order.
        if self.sport.startswith("americanfootball") and type(neutral) is not bool:
            return None
        params = self.artifact["parameters"]
        p = probability(ratings[h], ratings[a], 0 if neutral else params["home_advantage"])
        selection = self.aliases.get(price.selection, price.selection)
        if selection not in (h, a):
            return None
        return ModelEstimate(
            probability=Decimal(str(p if selection == h else 1 - p)),
            uncertainty=Decimal(str(self.artifact["uncertainty"])),
            model_name=self.artifact["model_name"],
            model_version=self.artifact["model_version"],
            feature_snapshot={
                "home_team": h,
                "away_team": a,
                "neutral_site": neutral,
                "source_checksum": self.artifact["source_checksum"],
            },
            # Baseline artifacts cannot bypass validation by editing a JSON flag.
            approved_for_betting=False,
        )
