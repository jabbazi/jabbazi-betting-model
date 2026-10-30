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


class BoostJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["NBA", "NFL"]
    slate_date: date
    game_ids: list[int] = Field(min_length=1, max_length=5)


@router.post("/v1/chatgpt/boost-paid-join-diagnostic", operation_id="diagnose_exact_paid_player_join")
def diagnose_join(body: BoostJoinRequest, authorization: Annotated[str | None, Header()] = None):
    """Private aggregate-only LAB/Sports join; never exposes odds or model rows."""
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .config import Settings
    from .vip.paid_models import read_paid_player_models
    from .boost_paid_join import reconcile_paid_player_research

    authorize(authorization)
    if len(set(body.game_ids)) != len(body.game_ids) or any(type(x) is not int or x <= 0 for x in body.game_ids):
        raise HTTPException(422, "Distinct positive game IDs required")
    settings = Settings.from_environment()
    if not settings.balldontlie_api_key or not settings.balldontlie_lab_api_key:
        raise HTTPException(503, "Separate LAB and Sports API credentials required")
    lab = read_paid_player_models(settings.balldontlie_lab_api_key, body.sport, body.slate_date)
    if not lab["coverage_complete"] or lab["state"] != "RESEARCH_ONLY":
        return JSONResponse({
            "sport": body.sport, "status": "UNAVAILABLE",
            "reason": lab["reason"] or "NO_VERIFIED_LAB_PREDICTIONS",
            "exact_identity_joins": 0, "betting_enabled": False,
            "calibrated_hit_probabilities_verified": False,
            "joint_probability_validated": False,
        }, headers=PRIVATE_HEADERS)
    provider = BallDontLieProvider(settings.balldontlie_api_key, budget=15)
    try:
        odds = collect_boost_odds(
            provider, BoostScope(SPORTS[body.sport]),
            game_ids=body.game_ids, max_pages_per_game=2,
        )
        if odds.coverage != "FULL" or odds.odds_rows == 0:
            return JSONResponse({
                "sport": body.sport, "status": "UNAVAILABLE",
                "reason": "INCOMPLETE_OR_EMPTY_SPORTS_API_PROPS",
                "exact_identity_joins": 0, "betting_enabled": False,
                "calibrated_hit_probabilities_verified": False,
                "joint_probability_validated": False,
            }, headers=PRIVATE_HEADERS)
        report = reconcile_paid_player_research(
            body.sport, lab["rows"], odds.rows, observed_at=datetime.now(UTC),
        )
        return JSONResponse({
            "sport": body.sport, "status": "RESEARCH_ONLY",
            "lab_predictions_seen": lab["predictions_seen"],
            "odds_rows_accepted": odds.odds_rows,
            "exact_identity_joins": report["unique_exact_identity_joins"],
            "identity_namespace_independently_verified": False,
            "calibrated_hit_probabilities_verified": False,
            "joint_probability_validated": False,
            "betting_enabled": False,
        }, headers=PRIVATE_HEADERS)
    finally:
        provider.close()


class GoatSportFeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["NBA", "NFL", "NHL"]
    slate_date: date
    max_games: int = Field(default=5, ge=1, le=10)


@router.post("/v1/chatgpt/boost-goat-feed-diagnostic", operation_id="diagnose_goat_sport_prop_feed")
def diagnose_goat(body: GoatSportFeedRequest, authorization: Annotated[str | None, Header()] = None):
    """Private GOAT Sports API acceptance; does not require LAB or approve models.

    Discovers the specified sport's games and checks actual paid player-prop
    responses. This endpoint does not call LAB, generate predictions, or place bets.
    """
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .config import Settings
    from tools.boost_live_acceptance import audit_sport
    from .boost_goat_model_map import summarize_goat_model_market_alignment

    authorize(authorization)
    key = Settings.from_environment().balldontlie_api_key
    if not key:
        raise HTTPException(503, "BALLDONTLIE Sports API credential unavailable")
    provider = BallDontLieProvider(key, budget=20)
    try:
        result = audit_sport(
            provider, sport=body.sport,
            calendar_date=body.slate_date, max_games=body.max_games,
        )
        # Only aggregate evidence, never raw vendor odds, player IDs, or secrets.
        complete = (
            result["coverage"] == "FULL"
            and result["games_eligible"] > 0
            and result["games_with_eligible_quotes"] == result["games_eligible"]
            and result["eligible_quote_rows"] > 0
            and not result["errors"]
        )
        return JSONResponse({
            "sport": body.sport,
            "slate_date": body.slate_date.isoformat(),
            "source": "BALLDONTLIE_SPORTS_API",
            "lab_required": False,
            "status": "RESEARCH_ONLY" if complete else "UNAVAILABLE",
            "reason": None if complete else "PAID_SPORT_PROP_COVERAGE_NOT_VERIFIED",
            "games_eligible": result["games_eligible"],
            "games_with_eligible_quotes": result["games_with_eligible_quotes"],
            "eligible_quote_rows": result["eligible_quote_rows"],
            "observed_market_breadth": result["observed_market_breadth"],
            "jabbazi_market_alignment": summarize_goat_model_market_alignment(
                body.sport, result["observed_market_breadth"],
            ),
            "coverage": result["coverage"],
            "errors": result["errors"],
            "jabbazi_exact_line_probabilities_verified": False,
            "joint_probability_validated": False,
            "betting_enabled": False,
            "production_approved": False,
            "observed_at": datetime.now(UTC).isoformat(),
        }, headers=PRIVATE_HEADERS)
    finally:
        provider.close()


class BoostRosterCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["NBA", "NFL"]
    slate_date: date
    max_games: int = Field(default=1, ge=1, le=2)
    max_prop_pages: int = Field(default=5, ge=1, le=5)


@router.post(
    "/v1/chatgpt/boost-roster-candidate-diagnostic",
    operation_id="diagnose_goat_player_identity_candidates",
)
def diagnose_roster_candidates(
    body: BoostRosterCandidateRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """Private GOAT-to-ESPN/nflverse roster candidate audit.

    Uses one requested sport and date, with bounded paid reads. Returns only
    counts and reason codes. Candidate matches are NOT verified crosswalks,
    fitted probabilities, or betting approval.
    """
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .config import Settings
    from tools.prepare_goat_roster_candidates import audit_date_candidates

    authorize(authorization)
    key = Settings.from_environment().balldontlie_api_key
    if not key:
        raise HTTPException(503, "BALLDONTLIE Sports API credential unavailable")
    provider = BallDontLieProvider(key, budget=15)
    try:
        report = audit_date_candidates(
            provider, sport=body.sport, calendar_date=body.slate_date,
            max_games=body.max_games, max_prop_pages=body.max_prop_pages,
        )
        # Whitelist fields. Never expose _private_candidates, vendor player
        # identities, source roster data, API responses, or provider secrets.
        return JSONResponse({
            "sport": body.sport,
            "slate_date": body.slate_date.isoformat(),
            "status": report.get("status", "UNAVAILABLE"),
            "reason": report.get("reason", "PRIVATE_SOURCE_UNAVAILABLE"),
            "games_considered": report.get("games_considered", 0),
            "eligible_quote_rows": report.get("eligible_quote_rows", 0),
            "provider_player_rows": report.get("provider_player_rows", 0),
            "identity_candidate_count": report.get("candidate_count", 0),
            "rejections": report.get("rejections", {}),
            "independently_verified_crosswalks": 0,
            "exact_model_inputs_verified": False,
            "calibrated_exact_line_probabilities_verified": False,
            "joint_probability_validated": False,
            "betting_enabled": False,
            "production_approved": False,
            "observed_at": datetime.now(UTC).isoformat(),
        }, headers=PRIVATE_HEADERS)
    finally:
        provider.close()
