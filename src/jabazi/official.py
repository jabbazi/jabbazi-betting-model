"""Owner-issued pick cards and immutable public history, independent of model approval.

No scanner candidate is automatically issued. Results are card returns at the
published price/stake, never a claim about a member's or owner's actual bankroll.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator
from sqlalchemy import select

from .config import Settings
from .persistence.store import events, clean, digest, Conflict, utc


class IssuePick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    card: Literal["main", "sprinkle"]
    sport: Literal["mlb", "nfl", "cfb", "nba", "tennis"]
    event_id: str = Field(min_length=1, max_length=120)
    event: str = Field(min_length=3, max_length=180)
    starts_at: AwareDatetime
    market: str = Field(min_length=1, max_length=80)
    selection: str = Field(min_length=1, max_length=160)
    line: Decimal | None = Field(default=None, allow_inf_nan=False)
    participant: str | None = Field(default=None, max_length=100)
    sportsbook: str = Field(min_length=1, max_length=80)
    decimal_odds: Decimal = Field(gt=1, le=10000, allow_inf_nan=False)
    minimum_decimal: Decimal = Field(gt=1, le=10000, allow_inf_nan=False)
    price_observed_at: AwareDatetime
    stake_units: Decimal = Field(gt=0, le=1, multiple_of=Decimal("0.05"), allow_inf_nan=False)
    reasoning: str = Field(min_length=20, max_length=700)
    evidence: str = Field(min_length=10, max_length=400)
    risks: str = Field(min_length=10, max_length=400)
    owner_reviewed: Literal[True]
    position_id: str | None = Field(default=None, min_length=8, max_length=64)

    @model_validator(mode="after")
    def constraints(self):
        if self.minimum_decimal > self.decimal_odds:
            raise ValueError("Offered price is beyond the play-to limit")
        if self.card == "sprinkle" and self.stake_units > Decimal("0.25"):
            raise ValueError("Sprinkles are limited to 0.25u")
        if self.sport == "cfb" and (self.participant or "player" in self.market.lower()):
            raise ValueError("College player props are excluded")
        return self


class PickUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)
    status: Literal["WATCH", "WITHDRAWN"]
    reason: str = Field(min_length=10, max_length=500)


class PickResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)
    result: Literal["win", "loss", "push", "void"]
    evidence: str = Field(min_length=10, max_length=500)
    correction_reason: str | None = Field(default=None, min_length=10, max_length=500)


def history(store, pick_id, conn=None):
    query = (
        select(events)
        .where(events.c.entity == pick_id, events.c.kind.in_(["official_pick", "official_update"]))
        .order_by(events.c.occurred_at, events.c.id)
    )
    if conn is not None:
        rows = [dict(r) for r in conn.execute(query).mappings()]
    else:
        with store.engine.connect() as connection:
            rows = [dict(r) for r in connection.execute(query).mappings()]
    return sorted(rows, key=lambda r: r["payload"]["revision"])


def issue(store, body, now=None):
    now = now or datetime.now(UTC)
    pick_id = "pick_" + digest(body.idempotency_key)[:24]
    submitted = clean(body.model_dump(exclude={"idempotency_key"}))
    with store.transaction() as conn:
        prior = history(store, pick_id, conn)
        if prior:
            if prior[0]["payload"]["submission"] != submitted:
                raise Conflict("Publication key reused with different card")
            return pick_id, False
        if body.starts_at <= now or not timedelta(0) <= now - body.price_observed_at <= timedelta(
            seconds=120
        ):
            raise ValueError("Verify a pregame price within the last 120 seconds before issuing")
        unit = Settings.from_environment().unit_size
        if not unit.is_finite() or unit <= 0:
            raise ValueError("Invalid unit size")
        if body.position_id:
            from .persistence.store import positions

            position = (
                conn.execute(select(positions).where(positions.c.id == body.position_id))
                .mappings()
                .first()
            )
            if not position:
                raise ValueError("Linked ledger position does not exist")
            p = position["payload"]
            for name, expected in (
                ("event", body.event_id),
                ("market", body.market),
                ("selection", body.selection),
                ("participant", body.participant),
                ("sportsbook", body.sportsbook),
            ):
                if p.get(name) != expected:
                    raise ValueError("Linked ledger contract differs from card")
            if (Decimal(p["line"]) if p.get("line") is not None else None) != body.line:
                raise ValueError("Linked ledger threshold differs from card")
        payload = {
            "revision": 1,
            "submission": submitted,
            "issued_at": now.isoformat(),
            "unit_size": str(unit),
            "stake_dollars": str((unit * body.stake_units).quantize(Decimal(".01"))),
            "status": "ACTIVE",
            "provenance": "OWNER_ISSUED",
            "valid_until": min(
                body.starts_at, body.price_observed_at + timedelta(seconds=120)
            ).isoformat(),
        }
        store._append(conn, "official_pick", pick_id, payload, digest(["official_pick", pick_id]))
    return pick_id, True


def change(store, pick_id, body, now=None, source="OWNER_REPORTED"):
    now = now or datetime.now(UTC)
    command = clean(body.model_dump(exclude={"idempotency_key"}))
    key = digest(["official_update", pick_id, body.idempotency_key])
    with store.transaction() as conn:
        rows = history(store, pick_id, conn)
        if not rows:
            raise LookupError("Unknown official pick")
        previous = next((r for r in rows if r["id"] == key), None)
        if previous:
            if previous["payload"]["command"] != command:
                raise Conflict("Update key reused with different evidence")
            return False
        if rows[-1]["payload"]["revision"] != body.expected_revision:
            raise Conflict("Card changed; refresh before updating")
        if isinstance(body, PickResult):
            results = [r for r in rows if r["payload"].get("result")]
            if results and not body.correction_reason:
                raise ValueError("Settlement correction requires a reason")
            if (
                datetime.fromisoformat(rows[0]["payload"]["submission"]["starts_at"]) > now
                and body.result != "void"
            ):
                raise ValueError("Cannot settle a game before its start")
            status = "SETTLED"
            details = {
                "result": body.result,
                "evidence": body.evidence,
                "correction_reason": body.correction_reason,
            }
        else:
            if any(r["payload"].get("result") for r in rows):
                raise ValueError("Settled cards require a settlement correction")
            if rows[-1]["payload"].get("status") == "WITHDRAWN":
                raise ValueError("A withdrawal cannot be erased")
            status, details = body.status, {"reason": body.reason}
        payload = {
            "revision": body.expected_revision + 1,
            "at": now.isoformat(),
            "status": status,
            "source": source,
            "command": command,
            **details,
        }
        store._append(conn, "official_update", pick_id, payload, key)
    return True


def card_view(store, pick_id, now=None):
    now = now or datetime.now(UTC)
    rows = history(store, pick_id)
    if not rows:
        raise LookupError("Unknown official pick")
    first, latest = rows[0]["payload"], rows[-1]["payload"]
    submitted = first["submission"]
    # Explicit public allowlist; personal ledger IDs and evidence refs stay private.
    keys = (
        "card",
        "sport",
        "event_id",
        "event",
        "starts_at",
        "market",
        "selection",
        "line",
        "participant",
        "sportsbook",
        "decimal_odds",
        "minimum_decimal",
        "price_observed_at",
        "stake_units",
        "reasoning",
        "risks",
    )
    status = latest["status"]
    if status == "ACTIVE" and datetime.fromisoformat(first["valid_until"]) <= now:
        status = "PRICE_EXPIRED"
    result = latest.get("result")
    units, price = Decimal(submitted["stake_units"]), Decimal(submitted["decimal_odds"])
    profit = (
        units * (price - 1)
        if result == "win"
        else -units
        if result == "loss"
        else Decimal(0)
        if result
        else None
    )
    from .operations import clv_for_entry

    measured = clv_for_entry(
        store,
        event_id=submitted["event_id"],
        market=submitted["market"],
        selection=submitted["selection"],
        line=Decimal(submitted["line"]) if submitted.get("line") is not None else None,
        participant=submitted.get("participant"),
        entry_decimal=submitted["decimal_odds"],
    )
    public_clv = clean(
        {
            k: measured[k]
            for k in (
                "status",
                "closing_probability",
                "probability_clv",
                "price_clv",
                "note",
                "reason",
            )
            if k in measured
        }
    )
    return {
        "clv": public_clv,
        **{k: submitted.get(k) for k in keys},
        "id": pick_id,
        "revision": latest["revision"],
        "issued_at": first["issued_at"],
        "valid_until": first["valid_until"],
        "unit_size": first["unit_size"],
        "stake_dollars": first["stake_dollars"],
        "status": status,
        "result": result,
        "profit_units": str(profit) if profit is not None else None,
        "withdrawn": any(r["payload"]["status"] == "WITHDRAWN" for r in rows),
        "reason": latest.get("reason"),
        "result_source": latest.get("source") if result else None,
        "correction_reason": latest.get("correction_reason"),
        "provenance": "OWNER_ISSUED",
        "model_approved": False,
    }


def all_cards(store):
    with store.engine.connect() as conn:
        ids = (
            conn.execute(
                select(events.c.entity)
                .where(events.c.kind == "official_pick")
                .order_by(events.c.occurred_at.desc(), events.c.id)
            )
            .scalars()
            .all()
        )
    return [card_view(store, key) for key in ids]


def performance(cards):
    summaries = {}
    for category in ("main", "sprinkle"):
        rows = [r for r in cards if r["card"] == category]
        settled = [r for r in rows if r["result"]]
        risked = sum(
            (Decimal(r["stake_units"]) for r in settled if r["result"] != "void"), Decimal(0)
        )
        profit = sum((Decimal(r["profit_units"]) for r in settled), Decimal(0))
        summaries[category] = {
            "issued": len(rows),
            "unsettled": len(rows) - len(settled),
            "wins": sum(r["result"] == "win" for r in settled),
            "losses": sum(r["result"] == "loss" for r in settled),
            "pushes": sum(r["result"] == "push" for r in settled),
            "voids": sum(r["result"] == "void" for r in settled),
            "withdrawn": sum(r["withdrawn"] for r in rows),
            "stake_units": str(risked),
            "profit_units": str(profit),
            "roi": str(profit / risked) if risked else None,
        }
    return summaries


def sync_ledger_results(store):
    """Mirror explicit ledger settlements; never guess scores or scrape results."""
    changed = 0
    for card in all_cards(store):
        source = history(store, card["id"])[0]["payload"]["submission"].get("position_id")
        if not source:
            continue
        records = [
            r
            for r in store.list_records("position_transition", 1000, entity=source)
            if r["payload"].get("state") == "settled"
        ]
        if not records:
            continue
        record = records[0]
        event_key = "ledger_" + digest(record["id"])[:56]
        updates = history(store, card["id"])
        if any(r["id"] == digest(["official_update", card["id"], event_key]) for r in updates):
            continue
        evidence = record["payload"]["evidence"]
        body = PickResult(
            idempotency_key=event_key,
            expected_revision=card["revision"],
            result=evidence["result"],
            evidence="Linked owner ledger settlement recorded "
            + utc(record["occurred_at"]).isoformat(),
            correction_reason="Linked ledger settlement was corrected" if card["result"] else None,
        )
        changed += change(store, card["id"], body, source="OWNER_LEDGER")
    return changed


def card_day(card):
    return (
        datetime.fromisoformat(card["starts_at"])
        .astimezone(ZoneInfo(Settings.from_environment().timezone))
        .date()
        .isoformat()
    )
