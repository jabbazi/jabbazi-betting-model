"""Private GPT Actions bridge. No placement, ledger editing, or Discord tools.

Requests/results are immutable DB evidence. Background execution is intentionally
at-most-once: a process interruption expires the job instead of silently charging
provider quota again. The client can explicitly request a new scan after expiry.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .config import Settings
from .persistence.store import events, digest, utc

router = APIRouter()
ORIGIN = "https://jabbazi-research-api.onrender.com"
PAGE_SIZE = 25
JOB_SECONDS = 600
MIN_INTERVAL = 120
RESULT_WAIT_SECONDS = 10
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Vary": "Authorization"}


def scanner_key() -> str:
    settings = Settings.from_environment()
    if len(settings.service_token) < 32:
        raise HTTPException(503, "Owner credential is not configured")
    if os.getenv("JABBAZI_CHATGPT_ENABLED", "true").lower() != "true":
        raise HTTPException(503, "ChatGPT scanner is disabled")
    version = os.getenv("JABBAZI_CHATGPT_TOKEN_VERSION", "1")
    # Domain-separated key cannot authenticate to the owner/admin API.
    return "jbg_" + hmac.new(
        settings.service_token.encode(),
        ("jabbazi:chatgpt:scan-and-read:" + version).encode(),
        hashlib.sha256,
    ).hexdigest()


def authorize(header: str | None):
    expected = scanner_key()
    supplied = header.removeprefix("Bearer ") if header and header.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Private scanner key required")


class ScanEverythingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class ScannerModelState(BaseModel):
    market_buckets: dict[str, Any] = Field(default_factory=dict)
    sport: str
    status: Literal["SHADOW_ONLY", "UNAVAILABLE"]
    approved_for_betting: Literal[False]
    version: str | None
    supported_markets: list[str]
    state_refreshed_at: str | None


class ScannerModelStatus(BaseModel):
    # GPT Actions requires explicit object properties in response schemas.
    models: list[ScannerModelState]
    errors: list[str]


class ScanPage(BaseModel):
    current_central_time: str | None = None
    scan_id: str
    status: Literal["RUNNING", "COMPLETE", "PARTIAL", "FAILED", "EXPIRED"]
    started_at: str
    generated_at: str | None = None
    checked_at: str
    poll_after_seconds: int | None = None
    page: int
    page_action_count: int = Field(0, description="Number of rows in this response's actions array; at most 25.")
    total_pages: int = 1
    next_page: int | None = None
    total_returned_actions: int = Field(0, description="Stored rows across ALL result pages, not just this page; at most 260.")
    total_actions: int = 0
    truncated: bool = False
    feeds_scanned: int = 0
    quotes_archived: int = 0
    credits_remaining: int | None = None
    model_coverage: dict[str, Any] = {}
    event_market_coverage: dict[str, Any] | None = None
    result_ordering: str | None = None
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    betting_enabled: Literal[False] = False
    scope: str = (
        "Full scan of active configured feeds within a 15-credit budget; NFL, MLB, CFB first. "
        "Odds coverage is not trained-model coverage. Research only; no bets or Discord posts."
    )


def store_factory():
    from .api import platform_store

    return platform_store()


def record(conn, kind, scan_id):
    return conn.execute(
        select(events).where(events.c.kind == kind, events.c.entity == scan_id)
    ).mappings().first()


def submit(store, scan_id, now=None):
    now = now or datetime.now(UTC)
    # Serialize acceptance across API instances. Duplicate ids never recharge.
    with store.transaction() as conn:
        if record(conn, "chatgpt_scan_request", scan_id):
            return False
        latest = conn.execute(
            select(events)
            .where(events.c.kind == "chatgpt_scan_request")
            .order_by(events.c.occurred_at.desc())
            .limit(1)
        ).mappings().first()
        if latest:
            age = (now - utc(latest["occurred_at"])).total_seconds()
            terminal = record(conn, "chatgpt_scan_result", latest["entity"])
            if age < MIN_INTERVAL or (not terminal and age < JOB_SECONDS):
                raise HTTPException(
                    429, "A recent scan exists. Read its result before requesting another.",
                    headers={"Retry-After": str(MIN_INTERVAL)},
                )
        store._append(
            conn, "chatgpt_scan_request", scan_id,
            {"started_at": now.isoformat(), "mode": "full", "max_credits": 15},
            digest(["chatgpt_scan_request", scan_id]),
        )
    return True


def run_background(scan_id):
    from .api import ScanRequest, perform_scan

    store = None
    try:
        # Require durable storage before consuming any provider quota.
        store = store_factory()
        result = perform_scan(
            ScanRequest(mode="full", credit_reserve=50, max_credits=15), model_first=True,
        )
        result["status"] = (
            "FAILED" if result["feeds_scanned"] == 0
            else "PARTIAL" if result["errors"] else "COMPLETE"
        )
    except Exception:
        result = {"status": "FAILED", "errors": ["Scan unavailable; no actionable output"]}
    try:
        if store is not None:
            store.append(
                "chatgpt_scan_result", scan_id, result,
                digest(["chatgpt_scan_result", scan_id]),
            )
    finally:
        if store is not None:
            store.close()


def present_action(value, now):
    # Results may be retrieved long after execution. Recheck every price.
    keys = (
        "event_id", "sport", "event", "market", "participant", "selection", "line",
        "best_sportsbook", "best_decimal", "source_timestamp", "starts_at",
        "consensus_probability", "model_probability", "model_version", "probability_edge",
        "expected_roi", "uncertainty", "reason", "market_relative_ev",
    )
    keys += ("v42_decision", "v42_reasons", "raw_model_probability", "calibrated_model_probability", "market_aware_probability",
             "market_no_vig_probability", "model_stage", "market_bucket", "feature_health",
             "anomaly_state", "anomaly_reasons", "model_market_gap", "model_lane_decision",
             "model_can_influence_cash", "watch_trigger", "calibration_bucket",
             "calibration_sample_size", "uncertainty_low", "uncertainty_high", "uncertainty_kind",
             "break_even_probability", "period", "second_best_decimal", "price_fragility",
             "research_priority_score", "research_priority_components", "source_provenance",
             "game_distribution", "fair_price", "play_to_price")
    row = {key: value.get(key) for key in keys}
    if not row["model_version"]:
        row.update(model_probability=None, probability_edge=None, expected_roi=None)
    fresh = False
    try:
        source = datetime.fromisoformat(value["source_timestamp"].replace("Z", "+00:00"))
        start = datetime.fromisoformat(value["starts_at"].replace("Z", "+00:00"))
        fresh = (
            0 <= (now - source).total_seconds() <= 120 and start > now
            and not value.get("stale", True) and not value.get("in_play", True)
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    row.update(
        decision="WATCH" if fresh else "STALE DATA",
        price_is_current=fresh,
        probability_status="SHADOW_ONLY" if row["model_probability"] is not None else "UNAVAILABLE",
        stake_dollars="0", maximum_playable_price=None,
    )
    if not fresh:
        row["model_lane_decision"] = "PASS"
        row["watch_trigger"] = "Refresh pregame prices"
    return row


def scan_page(store, scan_id, page=1, now=None):
    now = now or datetime.now(UTC)
    with store.engine.connect() as conn:
        request = record(conn, "chatgpt_scan_request", scan_id)
        result = record(conn, "chatgpt_scan_result", scan_id)
    if request is None:
        raise HTTPException(404, "Scan not found")
    expired = (now - utc(request["occurred_at"])).total_seconds() >= JOB_SECONDS
    payload = result["payload"] if result else {}
    rows = payload.get("actions", [])
    if page > max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE):
        raise HTTPException(404, "Result page not found")
    status = payload.get("status", "EXPIRED" if expired else "RUNNING")
    total = payload.get("total_actions", len(rows))
    page_rows = rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    from zoneinfo import ZoneInfo
    return ScanPage(
        current_central_time=now.astimezone(ZoneInfo("America/Chicago")).isoformat(),
        scan_id=scan_id, status=status, started_at=request["payload"]["started_at"],
        checked_at=now.isoformat(), generated_at=payload.get("generated_at"),
        poll_after_seconds=10 if status == "RUNNING" else None,
        page=page, page_action_count=len(page_rows),
        total_pages=max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE),
        next_page=page + 1 if page * PAGE_SIZE < len(rows) else None,
        total_returned_actions=len(rows), total_actions=total, truncated=total > len(rows),
        feeds_scanned=payload.get("feeds_scanned", 0),
        quotes_archived=payload.get("quotes_archived", 0),
        credits_remaining=payload.get("credits_remaining"),
        model_coverage=payload.get("model_coverage", {}),
        event_market_coverage=payload.get("event_market_coverage"),
        result_ordering=payload.get("result_ordering"),
        actions=[present_action(r, now) for r in page_rows],
        errors=payload.get("errors", []),
    )


@router.post(
    "/v1/chatgpt/scans", operation_id="scanEverything", tags=["chatgpt"],
    response_model=ScanPage,
    description="Start an owner-only full research scan. Uses up to 15 provider credits and archives results. Reuse the same request_id on retries. No wagers or Discord publishing.",
    openapi_extra={"x-openai-isConsequential": True},
)
def start_scan(body: ScanEverythingRequest, tasks: BackgroundTasks,
               authorization: Annotated[str | None, Header()] = None):
    authorize(authorization)
    if not Settings.from_environment().api_key:
        raise HTTPException(503, "Odds provider is not configured")
    store = store_factory()
    scan_id = str(body.request_id)
    try:
        accepted = submit(store, scan_id)
        output = scan_page(store, scan_id)
    finally:
        store.close()
    if accepted:
        tasks.add_task(run_background, scan_id)
    return JSONResponse(output.model_dump(), headers=PRIVATE_HEADERS)


@router.get(
    "/v1/chatgpt/scans/{scan_id}", operation_id="getScanResults", tags=["chatgpt"],
    response_model=ScanPage,
    description="Read a scan result page; waits up to 10 seconds if RUNNING. Continue reading the same scan_id. Each page has at most 25 actions; coverage counts span all pages. Never treat expired prices or SHADOW_ONLY probabilities as actionable picks.",
)
def get_results(scan_id: UUID, page: Annotated[int, Query(ge=1, le=11)] = 1,
                authorization: Annotated[str | None, Header()] = None):
    authorize(authorization)
    store = store_factory()
    try:
        # GPTs cannot reliably pause between tool calls. Bound the wait here,
        # below the Actions timeout, without starting another provider scan.
        deadline = time.monotonic() + RESULT_WAIT_SECONDS
        output = scan_page(store, str(scan_id), page)
        while output.status == "RUNNING":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # scan_page releases its DB connection before each pause. This
            # synchronous route runs in FastAPI's thread pool, not its event loop.
            time.sleep(min(1, remaining))
            output = scan_page(store, str(scan_id), page)
    finally:
        store.close()
    return JSONResponse(output.model_dump(), headers=PRIVATE_HEADERS)


@router.get(
    "/v1/chatgpt/model-status", operation_id="getScannerModelStatus", tags=["chatgpt"],
    response_model=ScannerModelStatus,
    description="Read model versions, supported markets, state refresh timestamps and research-only status. This does not scan odds or consume provider credits.",
)
def model_status(authorization: Annotated[str | None, Header()] = None):
    authorize(authorization)
    from .api import model_status_data

    output = ScannerModelStatus.model_validate(model_status_data())
    return JSONResponse(output.model_dump(exclude_unset=True), headers=PRIVATE_HEADERS)


@router.post("/v1/owner/chatgpt-key", include_in_schema=False)
def owner_key(authorization: Annotated[str | None, Header()] = None):
    from .api import require_auth

    require_auth(authorization)
    return JSONResponse({"api_key": scanner_key()}, headers=PRIVATE_HEADERS)


@router.get("/chatgpt/openapi.json", include_in_schema=False)
def action_schema():
    schema = get_openapi(
        title="JABBAZI Private Scanner", version="1.0.0",
        routes=[route for route in router.routes if "chatgpt" in getattr(route, "tags", [])],
        description="Private owner research. No wagering or publishing tools.",
    )
    schema["servers"] = [{"url": ORIGIN}]
    schema["components"]["securitySchemes"] = {
        "scannerKey": {"type": "http", "scheme": "bearer"}
    }
    schema["security"] = [{"scannerKey": []}]
    for path in schema["paths"].values():
        for operation in path.values():
            operation["parameters"] = [
                p for p in operation.get("parameters", []) if p["name"] != "authorization"
            ]
    return JSONResponse(schema)


@router.get("/chatgpt", include_in_schema=False)
def setup_page():
    return HTMLResponse(
        Path(__file__).with_name("static").joinpath("chatgpt.html").read_text(),
        headers={
            "Cache-Control": "no-store", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
            "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        },
    )


@router.get("/chatgpt/setup.js", include_in_schema=False)
def setup_script():
    return Response(
        Path(__file__).with_name("static").joinpath("chatgpt.js").read_text(),
        media_type="application/javascript", headers={"Cache-Control": "no-store"},
    )
