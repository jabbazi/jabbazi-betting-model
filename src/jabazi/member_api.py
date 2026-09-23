"""Read-only member portal. Deliberately separate from owner and scanner routes."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .discord_sheets import latest_sheet
from .member_access import exchange_ticket, hashed, portal_origin, validate_session, SESSION_SECONDS
from .sheet_images import (
    grouped_rows,
    shortlist_rows,
    featured_rows,
    selection_label,
    page_count,
    render_card,
    odds,
)

router = APIRouter()
STATIC = Path(__file__).with_name("static")
COOKIE = "__Host-jabbazi_member"
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' https://cdn.discordapp.com; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"


def store_for_request():
    from .api import platform_store

    return platform_store()


def require_member(request, store):
    try:
        return validate_session(store, request.cookies.get(COOKIE))
    except PermissionError:
        raise HTTPException(401, "Open a fresh private access link from !vip in Discord") from None


def same_origin(request):
    if request.headers.get("origin") != portal_origin():
        raise HTTPException(403, "Same-origin request required")


@router.get("/vip", include_in_schema=False)
def portal():
    return FileResponse(STATIC / "vip.html", headers={**HEADERS, "Content-Security-Policy": CSP})


@router.get("/vip/app.js", include_in_schema=False)
def script():
    return FileResponse(STATIC / "vip.js", media_type="application/javascript", headers=HEADERS)


@router.get("/vip/style.css", include_in_schema=False)
def style():
    return FileResponse(STATIC / "vip.css", media_type="text/css", headers=HEADERS)


@router.get("/vip/info", include_in_schema=False)
def public_info():
    store = store_for_request()
    try:
        records = store.list_records("member_brand", 1, entity="server")
        icon = records[0]["payload"].get("icon_url", "") if records else ""
        parsed = urlparse(icon)
        if parsed.scheme != "https" or parsed.hostname != "cdn.discordapp.com":
            icon = ""
        return JSONResponse({"name": "JABBAZI GURU", "icon_url": icon}, headers=HEADERS)
    finally:
        store.close()


class AccessRequest(BaseModel):
    ticket: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/v1/member/session", include_in_schema=False)
def sign_in(body: AccessRequest, request: Request):
    same_origin(request)
    store = store_for_request()
    try:
        try:
            session = exchange_ticket(store, body.ticket)
        except PermissionError:
            raise HTTPException(
                401, "This access link expired or was already used; type !vip again"
            ) from None
        response = JSONResponse({"signed_in": True, "expires_in": SESSION_SECONDS}, headers=HEADERS)
        response.set_cookie(
            COOKIE,
            session,
            max_age=SESSION_SECONDS,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response
    finally:
        store.close()


@router.post("/v1/member/logout", include_in_schema=False)
def sign_out(request: Request):
    same_origin(request)
    store = store_for_request()
    try:
        require_member(request, store)
        key = hashed(request.cookies[COOKIE])
        store.append("member_session_revoked", key, {}, hashed("member_session_revoked:" + key))
        response = JSONResponse({"signed_out": True}, headers=HEADERS)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
    finally:
        store.close()


def public_row(block):
    best, ref = block["best"], block["reference"]
    row = best or ref
    return {
        "event_id": block.get("event_id", ""),
        "event": block["event"],
        "starts_at": block.get("starts_at_utc"),
        "player": block.get("participant"),
        "selection": selection_label(best)
        if best
        else selection_label(ref, reference=True)
        if ref
        else "No supported selection",
        "market": row["market"] if row else None,
        "side": row["selection"] if row else None,
        "odds": odds(best["decimal_odds"]) if best else None,
        "book": best["book"] if best else None,
        "model_probability": float(best["research_probability"]) if best else None,
        "market_probability": float(row["market_no_vig_probability"]) if row else None,
        "market_reference": ref["selection"] if ref else None,
        "edge": block["edge"],
        "status": block["status"],
        "model_version": best.get("model_version") if best else None,
        "price_at": row.get("price_time_utc") if row else None,
    }


@router.get("/v1/member/sheets", include_in_schema=False)
def sheets(
    request: Request,
    sport: Literal["nfl", "mlb", "cfb"] = "mlb",
    tab: Literal["sheets", "moneylines", "props", "touchdowns"] = "sheets",
    market: str = "",
):
    store = store_for_request()
    try:
        principal = require_member(request, store)
        record = latest_sheet(store)
        if not record or not record["payload"]["healthy"]:
            return JSONResponse(
                {
                    "state": "UNAVAILABLE",
                    "rows": [],
                    "games": 0,
                    "notice": "No healthy recent snapshot. No picks are being generated.",
                },
                headers=HEADERS,
            )
        if len(market) > 80:
            raise HTTPException(422, "Invalid market")
        groups = (
            [0]
            if tab in ("sheets", "moneylines")
            else [2]
            if tab == "touchdowns"
            else [1, 2]
            if sport == "mlb"
            else [1]
        )
        if tab == "touchdowns" and sport != "nfl":
            groups = []
        if tab == "props" and sport == "cfb":
            groups = []
        pool = record["payload"]["rows"]
        if tab == "moneylines":
            pool = [r for r in pool if r["market"] == "h2h"]
        available_markets = sorted(
            {r["market"] for g in groups for r in grouped_rows(record, sport)[g]}
        )
        if market:
            pool = [r for r in pool if r["market"] == market]
        filtered = {**record, "payload": {**record["payload"], "rows": pool}}
        featured = {group: featured_rows(filtered, sport, group) for group in range(3)}
        rows = [public_row(b) for group in groups for b in featured[group]]
        # Do not return source dumps, model features, scanner controls, bankroll or ledger.
        return JSONResponse(
            {
                "state": "RESEARCH",
                "sport": sport,
                "tab": tab,
                "rows": rows,
                "markets": [m for m in available_markets if tab != "moneylines" or m == "h2h"],
                "games": len(featured[0]),
                "completed_at": record["payload"]["completed_at"],
                "server_time": datetime.now(UTC).isoformat(),
                "session_expires_at": principal["expires_at"],
                "partial": bool(record["payload"].get("truncated"))
                or tab in ("props", "touchdowns"),
                "coverage": record["payload"].get("event_market_coverage"),
                "image_pages": [page_count(filtered, sport, g, rows=featured[g]) for g in range(3)],
                "featured_only": True,
                "notice": "Experimental model estimates; showing only positive, supported research edges. Market is no-vig consensus. Edge is percentage-point difference, not ROI.",
            },
            headers=HEADERS,
        )
    finally:
        store.close()


@router.get("/v1/member/image/{sport}/{group}/{page}.png", include_in_schema=False)
def image(
    request: Request,
    sport: Literal["nfl", "mlb", "cfb"],
    group: int,
    page: int,
    featured: bool = False,
):
    store = store_for_request()
    try:
        require_member(request, store)
        record = latest_sheet(store)
        selected = featured_rows(record, sport, group) if featured and record else None
        if (
            not record
            or not record["payload"]["healthy"]
            or group not in (0, 1, 2)
            or not 1 <= page <= page_count(record, sport, group, rows=selected)
        ):
            raise HTTPException(404, "Sheet unavailable")
        return Response(
            render_card(record, sport, group, page=page, rows=selected),
            media_type="image/png",
            headers=HEADERS,
        )
    finally:
        store.close()


@router.get("/v1/member/learn", include_in_schema=False)
def learn(request: Request):
    store = store_for_request()
    try:
        require_member(request, store)
        path = Path(__file__).resolve().parents[2] / "docs/discord/learn-how-to.json"
        # Source checkout and production wheel/container layouts differ.
        if not path.exists():
            path = Path("/app/docs/discord/learn-how-to.json")
        return JSONResponse(json.loads(path.read_text()), headers=HEADERS)
    finally:
        store.close()
