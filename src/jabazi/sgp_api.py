"""Owner research endpoint. Only persisted scan legs can reach model inference."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

from .domain.shopping import PriceCard
from .models.team_elo import timestamp
from .research.same_game import evaluate_same_game

router = APIRouter()


class CombinedOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=64, max_length=64)
    quote_id: str = Field(min_length=1, max_length=200)
    sportsbook: str = Field(min_length=1, max_length=100)
    decimal_odds: Decimal = Field(gt=1, le=1000000, allow_inf_nan=False)
    quoted_at: AwareDatetime
    settlement: str = Field(min_length=1, max_length=100)


class SameGameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_id: UUID
    leg_indexes: list[Annotated[int, Field(ge=0, le=259, strict=True)]] = Field(
        min_length=2, max_length=4
    )
    offer: CombinedOffer | None = None


def price_from_row(row):
    return PriceCard(
        sport=row["sport"],
        event_id=row["event_id"],
        event=row["event"],
        market=row["market"],
        participant=row.get("participant"),
        selection=row["selection"],
        line=Decimal(str(row["line"])) if row.get("line") is not None else None,
        book_prices={},
        best_book=row.get("best_sportsbook", ""),
        best_decimal=Decimal(str(row.get("best_decimal", 2))),
        consensus_probability=Decimal(".5"),
        market_relative_ev=Decimal(0),
        sportsbook_disagreement=Decimal(0),
        stale=row.get("stale", True),
        in_play=row.get("in_play", False),
        quote_ids=(),
        observed_at=timestamp(row["observed_at"]),
        source_timestamp=timestamp(row["source_timestamp"]),
        starts_at=timestamp(row["starts_at"]) if row.get("starts_at") else None,
    )


def evaluate_request(body):
    from . import chatgpt_api as bridge
    from .api import _json
    from .models.registry import load_models

    store = bridge.store_factory()
    try:
        with store.engine.connect() as conn:
            result = bridge.record(conn, "chatgpt_scan_result", str(body.scan_id))
        if result is None:
            raise HTTPException(404, "Completed scan not found")
        payload = result["payload"]
        if payload.get("status") != "COMPLETE" or payload.get("errors"):
            raise HTTPException(409, "Healthy completed scan required")
        rows = payload.get("actions", [])
        if len(set(body.leg_indexes)) != len(body.leg_indexes) or any(
            i >= len(rows) for i in body.leg_indexes
        ):
            raise HTTPException(422, "Distinct retained scan row indexes required")
        try:
            prices = [price_from_row(rows[i]) for i in body.leg_indexes]
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise HTTPException(409, "Scan lacks complete leg evidence") from None
        models, errors = load_models(store)
        from .models.player_registry import load_player_models
        from .models.player_joint import load_joint_player_model

        player_models, player_errors = load_player_models(store)
        errors.extend(player_errors)
        output = evaluate_same_game(
            prices,
            models.get(prices[0].sport),
            now=datetime.now(UTC),
            offer=body.offer.model_dump(mode="json") if body.offer else None,
            player_models=player_models,
            joint_player=load_joint_player_model(),
        )
        output.update(
            scan_id=str(body.scan_id), leg_indexes=body.leg_indexes, model_load_errors=errors
        )
        return JSONResponse(_json(output), headers=bridge.PRIVATE_HEADERS)
    finally:
        store.close()


@router.post(
    "/v1/chatgpt/same-game-parlay",
    operation_id="evaluate_same_game_parlay",
    openapi_extra={"x-openai-isConsequential": False},
)
def evaluate(body: SameGameRequest, authorization: Annotated[str | None, Header()] = None):
    from .chatgpt_api import authorize

    authorize(authorization)
    return evaluate_request(body)
