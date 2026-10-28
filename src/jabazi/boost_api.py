"""Private, read-only, sport-specific BALLDONTLIE boost feed diagnostic.

This endpoint does not estimate probabilities or recommend wagers.
"""
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .boost_scope import BoostScope, SPORTS
from .boost_feed import collect_boost_odds
from .boost_market_coverage import summarize_prop_markets
from .providers.balldontlie import BallDontLieProvider

router = APIRouter()


class BoostFeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["NBA", "NFL", "NHL"]
    game_ids: list[int] = Field(min_length=1, max_length=25)


@router.post("/v1/chatgpt/boost-feed-diagnostic", operation_id="diagnose_sport_boost_feed")
def diagnose(body: BoostFeedRequest, authorization: Annotated[str | None, Header()] = None):
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .config import Settings

    authorize(authorization)
    if len(set(body.game_ids)) != len(body.game_ids) or any(
        isinstance(x, bool) or x <= 0 for x in body.game_ids
    ):
        raise HTTPException(422, "Distinct positive game IDs required")
    key = Settings.from_environment().balldontlie_api_key
    if not key:
        raise HTTPException(503, "BALLDONTLIE credential unavailable")
    provider = BallDontLieProvider(key, budget=30)
    try:
        report = collect_boost_odds(
            provider, BoostScope(SPORTS[body.sport]),
            game_ids=body.game_ids,
        )
        # Raw licensed odds are deliberately not exposed by this diagnostic.
        return JSONResponse({
            "sport": body.sport,
            "games_requested": report.games_requested,
            "games_succeeded": report.games_succeeded,
            "odds_rows": report.odds_rows,
            "raw_odds_rows": report.raw_odds_rows,
            "duplicate_rows": report.duplicate_rows,
            "invalid_rows": report.invalid_rows,
            "mismatched_game_rows": report.mismatched_game_rows,
            "stale_rows": report.stale_rows,
            "out_of_scope_rows": report.out_of_scope_rows,
            "observed_market_breadth": summarize_prop_markets(report.rows),
            "per_game_accepted_rows": {
                str(game_id): count for game_id, count in report.game_row_counts
            },
            "pages": report.pages,
            "coverage": report.coverage,
            "errors": report.errors,
            "player_probabilities_verified": False,
            "wager_recommendation": "UNAVAILABLE",
            "observed_at": datetime.now(UTC).isoformat(),
        }, headers=PRIVATE_HEADERS)
    finally:
        provider.close()


class BoostLabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["NBA", "NFL"]
    slate_date: date


@router.post("/v1/chatgpt/boost-lab-diagnostic", operation_id="diagnose_paid_lab_player_models")
def diagnose_lab(body: BoostLabRequest, authorization: Annotated[str | None, Header()] = None):
    """Authenticated, aggregate-only LAB probe, distinct from Sports API odds.

    LAB access is not JABBAZI exact-line calibration and cannot approve a bet.
    """
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .config import Settings
    from .vip.paid_models import read_paid_player_models

    authorize(authorization)
    key = Settings.from_environment().balldontlie_lab_api_key
    if not key:
        raise HTTPException(503, "LAB credential unavailable")
    report = read_paid_player_models(key, body.sport, body.slate_date)
    rows = report.get("rows", [])
    return JSONResponse({
        "sport": body.sport,
        "slate_date": report["slate_date"],
        "observed_at": report["observed_at"],
        "state": report["state"],
        "reason": report["reason"],
        "models_found": report["models_found"],
        "models_checked": report["models_checked"],
        "predictions_seen": report["predictions_seen"],
        "eligible_prediction_rows": len(rows),
        "rejected_prediction_rows": report.get("rows_rejected_missing_identity_or_signal", 0),
        "endpoint_authenticated": report["coverage_complete"],
        "saved_predictions_observed": report["state"] == "RESEARCH_ONLY" and bool(rows),
        "calibrated_exact_line_probabilities_verified": False,
        "joint_probability_calibration_verified": False,
        "betting_enabled": False,
        "wager_recommendation": "UNAVAILABLE",
    }, headers=PRIVATE_HEADERS)
