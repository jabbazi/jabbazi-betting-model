"""Authenticated HTTP bridge for the Jabbazi Scanner website.

This service exposes price-shopping decisions produced by the audited scanner. It
does not place wagers, manufacture Pikkit links, or upgrade the market prior into
an independently modeled BET_NOW recommendation.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .automation import AutomaticScanner
from .config import Settings


class ScanRequest(BaseModel):
    mode: Literal["quick", "full"] = "quick"
    credit_reserve: int = Field(default=50, ge=0, le=100000)
    max_credits: int = Field(default=15, ge=1, le=100)
    limit: int = Field(default=260, ge=1, le=260)


app = FastAPI(title="Jabbazi Model API", version="0.1.0")
from .ledger_api import router as ledger_router

app.include_router(ledger_router)
_scan_lock = threading.Lock()


def _authorized(authorization: str | None, settings: Settings) -> bool:
    if not settings.service_token or len(settings.service_token) < 32:
        return False
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        return False
    return hmac.compare_digest(authorization[len(prefix) :], settings.service_token)


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    return value


def _action(action) -> dict:
    card = action.price
    return {
        **_json(action.reliability),
        "sport": card.sport,
        "event_id": card.event_id,
        "event": card.event,
        "market": card.market,
        "participant": card.participant,
        "selection": card.selection,
        "line": _json(card.line),
        "decision": action.decision.value,
        "reason": action.reason,
        "best_sportsbook": card.best_book,
        "best_decimal": _json(card.best_decimal),
        "book_prices": _json(card.book_prices),
        "consensus_probability": _json(card.consensus_probability),
        "market_relative_ev": _json(card.market_relative_ev),
        "sportsbook_disagreement": _json(card.sportsbook_disagreement),
        "model_probability": _json(action.model_probability),
        "estimated_ev": _json(action.estimated_ev),
        "expected_roi": _json(action.expected_roi),
        "probability_edge": _json(action.probability_edge),
        "model_version": action.model_version,
        "reservation_id": action.reservation_id,
        "uncertainty": _json(action.uncertainty),
        "book_holds": _json(card.book_holds),
        "book_no_vig": _json(card.book_no_vig),
        "stake": _json(action.stake),
        "maximum_playable_decimal": _json(action.maximum_playable_decimal),
        "stale": card.stale,
        "in_play": card.in_play,
        "observed_at": card.observed_at.isoformat(),
        "source_timestamp": card.source_timestamp.isoformat(),
        "starts_at": card.starts_at.isoformat() if card.starts_at else None,
    }


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "service": "jabbazi-model"}


def require_auth(authorization):
    if not _authorized(authorization, Settings.from_environment()):
        raise HTTPException(status_code=401, detail="Authentication required")


def platform_store():
    from .persistence.store import Store
    from .config import load_dotenv

    load_dotenv()

    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if not url:
        raise HTTPException(status_code=503, detail="Platform database is not configured")
    if os.getenv("JABAZI_ENV") == "production" and not url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise HTTPException(status_code=503, detail="Production requires PostgreSQL")
    store = None
    try:
        store = Store(url)
        if not store.ready():
            raise ValueError("Schema unavailable")
        return store
    except Exception:
        if store is not None:
            store.close()
        raise HTTPException(status_code=503, detail="Platform database unavailable") from None


@app.get("/readyz")
def ready():
    store = platform_store()
    store.close()
    return {
        "database": "ready",
        "betting_enabled": False,
        "note": "Liveness and database readiness do not approve models",
    }


@app.get("/v1/research/prospective-validation")
def prospective_validation(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    from .research.prospective import validation_report
    store = platform_store()
    try:
        return validation_report(store)
    finally:
        store.close()


@app.get("/v1/model-status")
def model_status(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    return model_status_data()


def model_status_data():
    from .models.registry import load_models
    from .models.player_registry import load_player_models, player_status
    from .models.team_elo import SPORTS
    from .reliability.layer import status_buckets

    store = platform_store()
    try:
        models, errors = load_models(store)
        player_models, player_errors = load_player_models(store)
        from .research.prospective import validation_report
        prospective = validation_report(store)

        rows = []
        for sport in SPORTS.values():
            team_buckets = status_buckets(models[sport], prospective) if sport in models else {}
            team_stages = {bucket["stage"] for bucket in team_buckets.values()}
            team_status = (
                "PRODUCTION_APPROVED"
                if team_stages == {"PRODUCTION_APPROVED"} and team_stages
                else "LIMITED_LIVE"
                if "PRODUCTION_APPROVED" in team_stages or "LIMITED_LIVE" in team_stages
                else "VALIDATING"
                if "VALIDATING" in team_stages
                else "SHADOW_ONLY"
                if team_stages
                else "UNAVAILABLE"
            )
            pstatus = player_status(player_models, sport)
            rows.append(
                {
                    "market_buckets": team_buckets,
                    "player_market_buckets": pstatus["market_buckets"],
                    "sport": sport,
                    "status": team_status,
                    "approved_for_betting": bool(team_buckets)
                    and all(bucket["approved_for_betting"] for bucket in team_buckets.values()),
                    "version": models[sport].artifact["model_version"] if sport in models else None,
                    "supported_markets": sorted(models[sport].supported_markets)
                    if sport in models
                    else [],
                    "player_status": pstatus["status"],
                    "player_supported_markets": pstatus["supported_markets"],
                    "state_refreshed_at": models[sport].artifact.get("state_refreshed_at")
                    if sport in models
                    else None,
                }
            )
    finally:
        store.close()
    return {"models": rows, "errors": errors + player_errors}


@app.get("/v1/candidates")
def candidates(limit: int = 100, authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="Limit must be 1–1000")
    store = platform_store()
    try:
        return {"records": store.list_records("candidate", limit)}
    finally:
        store.close()


@app.get("/v1/odds")
def odds(limit: int = 100, authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="Limit must be 1–1000")
    store = platform_store()
    try:
        return {"records": store.list_records("odds_snapshot", limit)}
    finally:
        store.close()


@app.get("/v1/model-health")
def model_health(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    status = model_status_data()
    approved_team_buckets = sum(
        int(bucket.get("approved_for_betting") is True)
        for model in status["models"]
        for bucket in model.get("market_buckets", {}).values()
    )
    approved_player_buckets = sum(
        int(bucket.get("approved_for_betting") is True)
        for model in status["models"]
        for bucket in model.get("player_market_buckets", {}).values()
    )
    store = platform_store()
    try:
        return {
            "recent_scans": store.list_records("scan_run", 20),
            "production_team_market_buckets": approved_team_buckets,
            "production_player_market_buckets": approved_player_buckets,
            "model_status_errors": status.get("errors", []),
        }
    finally:
        store.close()


@app.get("/v1/operations")
def operations(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    from .runtime import doctor

    store = platform_store()
    try:
        return {
            "configuration": doctor(),
            "workers": store.list_records("worker_heartbeat", 10),
            "collectors": store.list_records("collector_run", 10),
            "deliveries": store.list_records("delivery_result", 20),
            "quota_reservations": store.list_records("quota_reservation", 20),
        }
    finally:
        store.close()


@app.get("/v1/closing-lines")
def closing_lines(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    store = platform_store()
    try:
        return {"records": store.list_records("closing_proxy", 100)}
    finally:
        store.close()


@app.get("/v1/performance")
def performance(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    from .performance import report

    store = platform_store()
    try:
        return report(store)
    finally:
        store.close()


@app.post("/v1/scans/run")
def run_scan(
    body: ScanRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    settings = Settings.from_environment()
    if not _authorized(authorization, settings):
        raise HTTPException(status_code=401, detail="Model authorization failed")
    return perform_scan(body)


def perform_scan(body: ScanRequest, *, model_first: bool = False, progress_callback=None) -> dict:
    """Shared scanner execution; callers must authorize before invoking."""
    settings = Settings.from_environment()
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="Odds provider is not configured")
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A scan is already running")
    try:
        result = AutomaticScanner(
            settings,
            settings.database_path,
            credit_reserve=body.credit_reserve,
            max_credits_per_run=body.max_credits,
            progress_callback=progress_callback,
        ).run(body.mode)
        actions = sorted(
            result.actions,
            # The chat has a bounded response: retain fitted model estimates
            # before market-only rows. This is coverage ordering, not bet ranking.
            key=lambda item: (
                bool(model_first and item.model_probability is not None and item.model_version),
                item.price.market_relative_ev,
            ),
            reverse=True,
        )[: body.limit]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": body.mode,
            "feeds_scanned": result.feeds_scanned,
            "quotes_archived": result.quotes_archived,
            "credits_remaining": result.credits_remaining,
            "event_market_coverage": result.event_market_coverage,
            "errors": list(result.errors),
            "model_coverage": {
                "modeled_actions": sum(a.model_probability is not None for a in result.actions),
                "unmodeled_actions": sum(a.model_probability is None for a in result.actions),
                "versions": sorted({a.model_version for a in result.actions if a.model_version}),
                "production_approved": any(
                    a.reliability.get("model_stage") == "PRODUCTION_APPROVED"
                    for a in result.actions
                    if a.model_probability is not None
                ),
                "production_approved_actions": sum(
                    a.reliability.get("model_stage") == "PRODUCTION_APPROVED"
                    for a in result.actions
                    if a.model_probability is not None
                ),
                "returned_modeled_actions": sum(a.model_probability is not None for a in actions),
                "returned_unmodeled_actions": sum(a.model_probability is None for a in actions),
            },
            "result_ordering": "model_coverage_first" if model_first else "market_relative_ev",
            "actions": [_action(action) for action in actions],
            "total_actions": len(result.actions),
            "returned_actions": len(actions),
            "arbitrages": _json([asdict(item) for item in result.arbitrages]),
            "disclaimer": "No wagers were placed. Market-only signals cannot become BET_NOW.",
        }
    except Exception:
        raise HTTPException(
            status_code=503, detail="Scan unavailable; no actionable output"
        ) from None
    finally:
        _scan_lock.release()


@app.get("/v1/owner/review")
def owner_review(
    sport: Literal["mlb", "nfl", "cfb"] | None = None,
    page: int = 1,
    authorization: Annotated[str | None, Header()] = None,
):
    require_auth(authorization)
    if not 1 <= page <= 400:
        raise HTTPException(status_code=422, detail="Page must be 1–400")
    from fastapi.responses import JSONResponse
    from .owner_review import review_snapshot

    store = platform_store()
    try:
        return JSONResponse(
            review_snapshot(store, sport=sport, page=page),
            headers={"Cache-Control": "no-store", "Vary": "Authorization"},
        )
    finally:
        store.close()


@app.get("/owner", include_in_schema=False)
def owner_page():
    from pathlib import Path
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        Path(__file__).with_name("static").joinpath("owner.html").read_text(),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
            "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        },
    )


@app.get("/owner/review.js", include_in_schema=False)
def owner_script():
    from pathlib import Path
    from fastapi.responses import Response

    return Response(
        Path(__file__).with_name("static").joinpath("review.js").read_text(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


from .chatgpt_api import router as chatgpt_router

app.include_router(chatgpt_router)

from .scanner_mcp import router as scanner_mcp_router

app.include_router(scanner_mcp_router)

from .member_api import router as member_router

app.include_router(member_router)


@app.post('/v1/research/source-picks')
def source_pick(body: dict, authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    from .research.evidence import freeze_source
    store=platform_store()
    try:
        return {'id':freeze_source(store,body),'status':'DISCOVERY_INPUT_ONLY'}
    except ValueError as exc:
        raise HTTPException(422,'Invalid source-pick evidence') from exc
    finally:
        store.close()


@app.get('/v1/research/source-picks')
def source_picks(authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    store=platform_store()
    try:return {'records':store.list_records('source_pick',100)}
    finally:store.close()


@app.get('/v1/research/model-diagnostics/{event_id}')
def model_diagnostics(event_id: str, authorization: Annotated[str | None, Header()] = None):
    require_auth(authorization)
    store=platform_store()
    try:
        return {'event_id':event_id,'predictions':store.list_records('model_prediction',100,entity=event_id),
                'note':'Owner-only frozen inference evidence; never backfill missing inputs'}
    finally:store.close()
