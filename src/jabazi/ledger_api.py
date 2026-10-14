"""Owner-reported betting records. These endpoints never execute sportsbook bets."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime
from .persistence.store import Conflict

router = APIRouter(prefix="/v1/ledger", tags=["Owner ledger"])
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class Placement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sport: str = Field(min_length=1, max_length=80)
    event_id: str = Field(min_length=1, max_length=120)
    market: str = Field(min_length=1, max_length=100)
    selection: str = Field(min_length=1, max_length=160)
    participant: str | None = Field(default=None, max_length=120)
    line: Decimal | None = Field(default=None, allow_inf_nan=False)
    sportsbook: str = Field(min_length=1, max_length=100)
    decimal_odds: Decimal = Field(gt=1, le=1000000, allow_inf_nan=False)
    stake: Money
    placed_at: AwareDatetime
    ticket_reference: str = Field(min_length=1, max_length=200)
    origin: Literal["user", "scanner"] = "user"
    parlay: bool = False
    theses: list[str] = Field(min_length=1, max_length=20)


class Settlement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    result: Literal["win", "loss", "push", "void"]
    evidence_reference: str = Field(min_length=1, max_length=200)
    correction_reason: str | None = Field(default=None, min_length=1, max_length=500)


def store_for(authorization):
    from .api import require_auth, platform_store

    require_auth(authorization)
    return platform_store()


@router.post("/import")
def import_placement(body: Placement, authorization: Annotated[str | None, Header()] = None):
    from datetime import UTC
    from zoneinfo import ZoneInfo
    from .config import Settings

    store = store_for(authorization)
    try:
        if body.placed_at > datetime.now(UTC):
            raise HTTPException(422, "A reported placement cannot be in the future")
        settings = Settings.from_environment()
        if not settings.unit_size.is_finite() or settings.unit_size <= 0:
            raise HTTPException(503, "Unit setting is invalid")
        payload = {
            **body.model_dump(exclude={"idempotency_key"}),
            "event": body.event_id,
            "players": [body.participant] if body.participant else [],
            "betting_date": body.placed_at.astimezone(ZoneInfo(settings.timezone))
            .date()
            .isoformat(),
            "stake_units": body.stake / settings.unit_size,
            "unit_size": settings.unit_size,
            "provenance": "OWNER_REPORTED",
            "actor": "authenticated_owner",
            "model_probability": None,
            "model_version": None,
            "note": "Reported historical placement; no sportsbook transaction executed",
        }
        created = store.import_placement(body.idempotency_key, payload)
        return {
            "id": body.idempotency_key,
            "created": created,
            "status": "placed",
            "provenance": "OWNER_REPORTED",
        }
    except Conflict:
        raise HTTPException(409, "Idempotency key conflicts with existing evidence") from None
    finally:
        store.close()


@router.get("")
def ledger(limit: int = 100, authorization: Annotated[str | None, Header()] = None):
    store = store_for(authorization)
    try:
        if not 1 <= limit <= 1000:
            raise HTTPException(422, "Limit must be 1–1000")
        return {"positions": store.list_positions(limit), "open_exposure": store.open_exposure()}
    finally:
        store.close()


@router.post("/{position_id}/settle")
def settle(
    position_id: str, body: Settlement, authorization: Annotated[str | None, Header()] = None
):
    store = store_for(authorization)
    try:
        row = store.get_position(position_id)
        if row is None:
            raise HTTPException(404, "Unknown position")
        amount, price = Decimal(row["payload"]["stake"]), Decimal(row["payload"]["decimal_odds"])
        profit = (
            amount * (price - 1)
            if body.result == "win"
            else -amount
            if body.result == "loss"
            else Decimal(0)
        )
        profit = profit.quantize(Decimal(".01"))
        evidence = {**body.model_dump(exclude={"idempotency_key"}), "profit": str(profit)}
        store.transition(
            position_id,
            "settled",
            actor="authenticated_owner",
            evidence=evidence,
            event_key=body.idempotency_key,
        )
        return {
            "id": position_id,
            "state": "settled",
            "profit": str(profit),
            "provenance": "OWNER_REPORTED",
        }
    except Conflict:
        raise HTTPException(409, "Idempotency key conflicts with existing evidence") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        store.close()


@router.get("/{position_id}/history")
def history(position_id: str, authorization: Annotated[str | None, Header()] = None):
    store = store_for(authorization)
    try:
        return {"events": store.list_records(limit=1000, entity=position_id)}
    finally:
        store.close()


@router.get("/{position_id}/clv")
def clv(position_id: str, authorization: Annotated[str | None, Header()] = None):
    from .operations import clv_for_entry

    store = store_for(authorization)
    try:
        row = store.get_position(position_id)
        if row is None:
            raise HTTPException(404, "Unknown position")
        p = row["payload"]
        if not all(k in p for k in ("market", "selection")):
            return {"status": "UNAVAILABLE", "reason": "Entry contract details missing"}
        return clv_for_entry(
            store,
            event_id=p["event"],
            market=p["market"],
            selection=p["selection"],
            line=Decimal(p["line"]) if p.get("line") is not None else None,
            participant=p.get("participant"),
            entry_decimal=p["decimal_odds"],
        )
    finally:
        store.close()
