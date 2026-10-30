"""Leakage-resistant MLB moneyline Elo model and artifact trainer."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jabazi.domain.shopping import PriceCard
from jabazi.providers.sportsdataio import HistoricalGame

from .base import ModelEstimate, ProbabilityModel


def _probability(home_rating: float, away_rating: float, home_advantage: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(home_rating + home_advantage - away_rating) / 400.0))


def _american_probability(price: Decimal) -> float | None:
    if price == 0:
        return None
    value = float(price)
    return (-value / (-value + 100.0)) if value < 0 else (100.0 / (value + 100.0))


def _market_home_probability(game: HistoricalGame) -> float | None:
    if game.home_moneyline is None or game.away_moneyline is None:
        return None
    home = _american_probability(game.home_moneyline)
    away = _american_probability(game.away_moneyline)
    if home is None or away is None or home + away <= 0:
        return None
    return home / (home + away)


def _brier(predictions: list[float], outcomes: list[int]) -> float:
    return sum(
        (prediction - outcome) ** 2 for prediction, outcome in zip(predictions, outcomes)
    ) / len(outcomes)


def _log_loss(predictions: list[float], outcomes: list[int]) -> float:
    clipped = [min(1 - 1e-9, max(1e-9, value)) for value in predictions]
    return -sum(
        outcome * math.log(value) + (1 - outcome) * math.log(1 - value)
        for value, outcome in zip(clipped, outcomes)
    ) / len(outcomes)


@dataclass(frozen=True)
class EloArtifact:
    model_name: str
    model_version: str
    trained_at: str
    seasons: list[int]
    holdout_season: int
    games_trained: int
    games_validated: int
    market_comparisons: int
    home_advantage: float
    k_factor: float
    uncertainty: float
    brier: float
    log_loss: float
    market_brier: float | None
    market_log_loss: float | None
    approved_for_betting: bool
    validation_reasons: list[str]
    team_ratings: dict[str, float]
    source_checksum: str


def train_mlb_elo(source: str | Path, destination: str | Path) -> EloArtifact:
    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    games = [
        HistoricalGame(
            game_id=str(row["game_id"]),
            starts_at=str(row["starts_at"]),
            season=int(row["season"]),
            away_team=str(row["away_team"]),
            home_team=str(row["home_team"]),
            away_score=int(row["away_score"]),
            home_score=int(row["home_score"]),
            away_moneyline=Decimal(str(row["away_moneyline"]))
            if row.get("away_moneyline")
            else None,
            home_moneyline=Decimal(str(row["home_moneyline"]))
            if row.get("home_moneyline")
            else None,
        )
        for row in payload.get("games", [])
    ]
    games.sort(key=lambda game: (game.starts_at, game.game_id))
    seasons = sorted({game.season for game in games})
    if len(seasons) < 3:
        raise ValueError("At least three seasons are required")
    holdout = seasons[-1]
    ratings: dict[str, float] = {}
    home_advantage, k_factor = 24.0, 18.0
    predictions: list[float] = []
    market_predictions: list[float] = []
    paired_model_predictions: list[float] = []
    market_outcomes: list[int] = []
    outcomes: list[int] = []
    trained = 0
    for game in games:
        home_rating = ratings.get(game.home_team, 1500.0)
        away_rating = ratings.get(game.away_team, 1500.0)
        probability = _probability(home_rating, away_rating, home_advantage)
        outcome = int(game.home_win)
        if game.season == holdout:
            predictions.append(probability)
            outcomes.append(outcome)
            market = _market_home_probability(game)
            if market is not None:
                market_predictions.append(market)
                paired_model_predictions.append(probability)
                market_outcomes.append(outcome)
        else:
            trained += 1
        change = k_factor * (outcome - probability)
        ratings[game.home_team] = home_rating + change
        ratings[game.away_team] = away_rating - change
    if not predictions:
        raise ValueError("Holdout season has no completed games")
    brier, log_loss = _brier(predictions, outcomes), _log_loss(predictions, outcomes)
    market_brier = _brier(market_predictions, market_outcomes) if market_predictions else None
    market_log_loss = _log_loss(market_predictions, market_outcomes) if market_predictions else None
    reasons: list[str] = []
    if len(predictions) < 500:
        reasons.append("fewer than 500 holdout games")
    if len(market_predictions) < 300:
        reasons.append("fewer than 300 no-vig market comparisons")
    paired_brier = _brier(paired_model_predictions, market_outcomes) if market_outcomes else None
    paired_log_loss = (
        _log_loss(paired_model_predictions, market_outcomes) if market_outcomes else None
    )
    if market_brier is None or paired_brier >= market_brier:
        reasons.append("Brier score did not beat the no-vig market")
    if market_log_loss is None or paired_log_loss >= market_log_loss:
        reasons.append("log loss did not beat the no-vig market")
    reasons.append("Legacy trainer is research-only; timestamp and prospective validation required")
    artifact = EloArtifact(
        model_name="mlb_moneyline_elo",
        model_version="0.1.0",
        trained_at=datetime.now(UTC).isoformat(),
        seasons=seasons,
        holdout_season=holdout,
        games_trained=trained,
        games_validated=len(predictions),
        market_comparisons=len(market_predictions),
        home_advantage=home_advantage,
        k_factor=k_factor,
        uncertainty=0.02,
        brier=brier,
        log_loss=log_loss,
        market_brier=market_brier,
        market_log_loss=market_log_loss,
        approved_for_betting=not reasons,
        validation_reasons=reasons,
        team_ratings={key: round(value, 6) for key, value in sorted(ratings.items())},
        source_checksum=hashlib.sha256(raw).hexdigest(),
    )
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(artifact), indent=2, sort_keys=True), encoding="utf-8")
    return artifact


class MlbMoneylineEloModel(ProbabilityModel):
    sport = "baseball_mlb"
    supported_markets = frozenset({"h2h"})

    def __init__(self, artifact_path: str | Path) -> None:
        self.artifact_path = Path(artifact_path)
        payload = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        self.artifact = EloArtifact(**payload)

    def estimate(self, price: PriceCard) -> ModelEstimate | None:
        if price.sport != self.sport or price.market not in self.supported_markets:
            return None
        if " @ " not in price.event:
            return None
        away, home = (value.strip() for value in price.event.split(" @ ", 1))
        ratings = self.artifact.team_ratings
        if home not in ratings or away not in ratings:
            return None
        home_probability = _probability(ratings[home], ratings[away], self.artifact.home_advantage)
        if price.selection == home:
            probability = home_probability
        elif price.selection == away:
            probability = 1.0 - home_probability
        else:
            return None
        return ModelEstimate(
            probability=Decimal(str(probability)),
            uncertainty=Decimal(str(self.artifact.uncertainty)),
            model_name=self.artifact.model_name,
            model_version=self.artifact.model_version,
            feature_snapshot={
                "home_team": home,
                "away_team": away,
                "home_rating": ratings[home],
                "away_rating": ratings[away],
                "home_advantage": self.artifact.home_advantage,
                "source_checksum": self.artifact.source_checksum,
            },
            approved_for_betting=self.artifact.approved_for_betting,
        )
