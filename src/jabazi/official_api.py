"""Owner-only issuance plus read-only, role-checked member cards and results."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import official
from .member_api import HEADERS, require_member, store_for_request
from .persistence.store import Conflict

router = APIRouter()


def owner_store(authorization):
    from .api import require_auth, platform_store

    require_auth(authorization)
    return platform_store()


def error(exc):
    return HTTPException(
        409 if isinstance(exc, Conflict) else 404 if isinstance(exc, LookupError) else 422, str(exc)
    )


@router.post("/v1/official", tags=["Official cards"])
def issue(body: official.IssuePick, authorization: Annotated[str | None, Header()] = None):
    store = owner_store(authorization)
    try:
        pick_id, created = official.issue(store, body)
        return {"created": created, "pick": official.card_view(store, pick_id)}
    except (ValueError, LookupError) as exc:
        raise error(exc) from None
    finally:
        store.close()


@router.post("/v1/official/{pick_id}/update", tags=["Official cards"])
def update(
    pick_id: str, body: official.PickUpdate, authorization: Annotated[str | None, Header()] = None
):
    store = owner_store(authorization)
    try:
        official.change(store, pick_id, body)
        return official.card_view(store, pick_id)
    except (ValueError, LookupError) as exc:
        raise error(exc) from None
    finally:
        store.close()


@router.post("/v1/official/{pick_id}/result", tags=["Official cards"])
def result(
    pick_id: str, body: official.PickResult, authorization: Annotated[str | None, Header()] = None
):
    store = owner_store(authorization)
    try:
        official.change(store, pick_id, body)
        return official.card_view(store, pick_id)
    except (ValueError, LookupError) as exc:
        raise error(exc) from None
    finally:
        store.close()


@router.get("/v1/official", tags=["Official cards"])
def owner_cards(authorization: Annotated[str | None, Header()] = None):
    store = owner_store(authorization)
    try:
        cards = official.all_cards(store)
        return JSONResponse(
            {"cards": cards, "performance": official.performance(cards)}, headers=HEADERS
        )
    finally:
        store.close()


@router.get("/v1/member/cards", include_in_schema=False)
def cards(request: Request, day: str = "", page: int = 1):
    store = store_for_request()
    try:
        principal = require_member(request, store)
        if not 1 <= page <= 10000:
            raise HTTPException(422, "Invalid page")
        if day:
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(422, "Use YYYY-MM-DD") from None
        all_rows = official.all_cards(store)
        selected = [r for r in all_rows if not day or official.card_day(r) == day]
        from .config import Settings

        return JSONResponse(
            {
                "cards": selected[(page - 1) * 50 : page * 50],
                "total": len(selected),
                "page": page,
                "has_more": page * 50 < len(selected),
                "performance": official.performance(all_rows),
                "server_time": datetime.now(UTC).isoformat(),
                "session_expires_at": principal["expires_at"],
                "timezone": Settings.from_environment().timezone,
                "notice": "Owner-issued card record at published prices and units. Not personal account returns. All issued cards remain, including withdrawals, losses and corrections. Voids excluded from ROI stake.",
            },
            headers=HEADERS,
        )
    finally:
        store.close()


@router.get("/v1/member/cards/{pick_id}/history", include_in_schema=False)
def card_history(pick_id: str, request: Request):
    store = store_for_request()
    try:
        require_member(request, store)
        rows = official.history(store, pick_id)
        if not rows:
            raise HTTPException(404, "Unknown official pick")
        return JSONResponse(
            {
                "events": [
                    {
                        k: r["payload"].get(k)
                        for k in (
                            "revision",
                            "issued_at",
                            "at",
                            "status",
                            "reason",
                            "result",
                            "source",
                            "correction_reason",
                        )
                    }
                    for r in rows
                ]
            },
            headers=HEADERS,
        )
    finally:
        store.close()


@router.get("/owner/picks", include_in_schema=False)
def page():
    return FileResponse(
        Path(__file__).with_name("static") / "picks-owner.html",
        headers={
            **HEADERS,
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        },
    )


@router.get("/owner/picks.js", include_in_schema=False)
def script():
    return FileResponse(
        Path(__file__).with_name("static") / "picks-owner.js",
        media_type="application/javascript",
        headers=HEADERS,
    )
