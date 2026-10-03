"""SportsDataIO MLB historical-results adapter."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class HistoricalGame:
    game_id: str
    starts_at: str
    season: int
    away_team: str
    home_team: str
    away_score: int
    home_score: int
    away_moneyline: Decimal | None = None
    home_moneyline: Decimal | None = None

    @property
    def home_win(self) -> bool:
        return self.home_score > self.away_score


def _first(payload: dict, *names: str):
    for name in names:
        value = payload.get(name)
        if value is not None:
            return value
    return None


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed != 0 else None


def _parse_game(item: dict, season: int) -> HistoricalGame | None:
    game_id = _first(item, "GameID", "GameId", "GlobalGameID", "id")
    starts_at = _first(item, "DateTime", "Day", "GameDate", "starts_at")
    away = _first(item, "AwayTeam", "AwayTeamKey", "away_team")
    home = _first(item, "HomeTeam", "HomeTeamKey", "home_team")
    away_score = _first(item, "AwayTeamRuns", "AwayTeamScore", "away_score")
    home_score = _first(item, "HomeTeamRuns", "HomeTeamScore", "home_score")
    status = str(_first(item, "Status", "GameStatus", "status") or "").lower()
    if not all(
        value is not None for value in (game_id, starts_at, away, home, away_score, home_score)
    ):
        return None
    if status and status not in {"final", "f", "completed", "closed"}:
        return None
    try:
        away_runs, home_runs = int(away_score), int(home_score)
    except (TypeError, ValueError):
        return None
    if away_runs == home_runs:
        return None
    return HistoricalGame(
        game_id=str(game_id),
        starts_at=str(starts_at),
        season=season,
        away_team=str(away).strip(),
        home_team=str(home).strip(),
        away_score=away_runs,
        home_score=home_runs,
        away_moneyline=_decimal(_first(item, "AwayTeamMoneyLine", "AwayMoneyLine")),
        home_moneyline=_decimal(_first(item, "HomeTeamMoneyLine", "HomeMoneyLine")),
    )


class SportsDataIOMlbProvider:
    base_url = "https://api.sportsdata.io/v3/mlb/scores/json/Games"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("JABBAZI_SPORTSDATAIO_API_KEY is required")
        self._api_key = api_key

    def games(self, season: int) -> list[HistoricalGame]:
        request = urllib.request.Request(
            f"{self.base_url}/{season}",
            headers={"Ocp-Apim-Subscription-Key": self._api_key},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        if not isinstance(payload, list):
            raise TypeError("Unexpected SportsDataIO games response")
        return [
            game
            for item in payload
            if isinstance(item, dict) and (game := _parse_game(item, season)) is not None
        ]

    def backfill(self, seasons: list[int], output: str | Path) -> int:
        games: dict[str, HistoricalGame] = {}
        for season in sorted(set(seasons)):
            for game in self.games(season):
                games[game.game_id] = game
        rows = []
        for game in sorted(games.values(), key=lambda value: (value.starts_at, value.game_id)):
            row = asdict(game)
            row["away_moneyline"] = (
                str(game.away_moneyline) if game.away_moneyline is not None else None
            )
            row["home_moneyline"] = (
                str(game.home_moneyline) if game.home_moneyline is not None else None
            )
            rows.append(row)
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "provider": "sportsdataio",
                    "sport": "baseball_mlb",
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "seasons": sorted(set(seasons)),
                    "games": rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return len(rows)
