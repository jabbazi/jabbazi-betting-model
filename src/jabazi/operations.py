"""Audited collection helpers; credentials never enter stored request metadata."""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from .domain.models import Quote, DataQuality
from .domain.shopping import build_price_cards
from .persistence.store import digest, events
from .research.closing import closing_proxy
from sqlalchemy import select


def monthly_credit_limit():
    value = int(os.getenv("JABBAZI_MONTHLY_CREDIT_LIMIT", "3000"))
    if not 1 <= value <= 10000000:
        raise ValueError("Monthly credit limit must be 1–10000000")
    return value


def reserve_request(store, amount, *, key=None, now=None):
    return store.claim_credits(
        "the_odds_api",
        amount,
        monthly_limit=monthly_credit_limit(),
        key=key or uuid.uuid4().hex,
        now=now,
    )


def quote_from_record(record):
    value = dict(record)
    for name in ("observed_at", "source_timestamp", "commence_time"):
        if value.get(name):
            value[name] = datetime.fromisoformat(value[name])
    value["decimal_odds"] = Decimal(value["decimal_odds"])
    value["line"] = Decimal(value["line"]) if value.get("line") is not None else None
    value["quality"] = DataQuality(value["quality"])
    return Quote(**value)


def archived_quotes(store, event_id):
    # No fixed 1000-row truncation: a full pre-close market must remain complete.
    with store.engine.connect() as conn:
        rows = conn.execute(
            select(events.c.payload).where(
                events.c.kind == "odds_snapshot", events.c.entity == event_id
            )
        ).scalars()
        return tuple(quote_from_record(row) for row in rows)


def finalize_closing(store, event_id, starts_at, *, now=None):
    now = now or datetime.now(UTC)
    if now < starts_at:
        return 0
    quotes = archived_quotes(store, event_id)
    from datetime import timedelta

    cards = build_price_cards(
        quotes, stale_after_seconds=Decimal(120), now=starts_at - timedelta(microseconds=1)
    )
    recorded = 0
    for card in cards:
        if card.starts_at != starts_at:
            continue
        result = closing_proxy(
            quotes,
            starts_at=starts_at,
            now=now,
            event_id=event_id,
            market=card.market,
            selection=card.selection,
            line=card.line,
            participant=card.participant,
        )
        if result["status"] != "CLOSING_PROXY":
            continue
        payload = {
            **result,
            "sport": card.sport,
            "event_id": event_id,
            "market": card.market,
            "selection": card.selection,
            "participant": card.participant,
        }
        key = digest(
            [
                "closing_proxy",
                event_id,
                starts_at.isoformat(),
                card.market,
                card.selection,
                str(card.line),
                card.participant,
            ]
        )
        # First eligible closure is immutable; later discrepancies are separate evidence.
        existing = store.list_records("closing_proxy", 1000, entity=event_id)
        if any(r["id"] == key for r in existing):
            continue
        if store.append("closing_proxy", event_id, payload, key):
            recorded += 1
    return recorded


def clv_for_entry(store, *, event_id, market, selection, line, participant, entry_decimal):
    matches = [
        r["payload"]
        for r in store.list_records("closing_proxy", 1000, entity=event_id)
        if r["payload"]["market"] == market
        and r["payload"]["selection"] == selection
        and r["payload"].get("participant") == participant
        and (Decimal(r["payload"]["line"]) if r["payload"].get("line") is not None else None)
        == line
    ]
    if len(matches) != 1:
        return {"status": "UNAVAILABLE", "reason": "Exactly one comparable closing proxy required"}
    price = Decimal(entry_decimal)
    if not price.is_finite() or price <= 1:
        raise ValueError("Valid entry decimal odds required")
    close = matches[0]
    p = Decimal(close["probability"])
    return {
        "status": "CLOSING_PROXY",
        "closing_probability": p,
        "probability_clv": p - 1 / price,
        "price_clv": price * p - 1,
        "closing": close,
        "note": "No line CLV inferred across different thresholds",
    }


class ClosingCollector:
    """Two deliberate pre-start snapshots per event, with durable request claims."""

    def __init__(self, store, api_key, *, provider_factory=None):
        from .providers.the_odds_api import TheOddsApiProvider

        self.store = store
        self.api_key = api_key
        self.provider_factory = provider_factory or TheOddsApiProvider

    def run(self, now=None):
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Aware collector time required")
        if not self.api_key:
            return {"status": "UNAVAILABLE", "reason": "Odds provider is not configured"}
        owner = uuid.uuid4().hex
        if not self.store.acquire_lease("closing_collector", owner, 600):
            return {"status": "BUSY"}
        report = {"status": "HEALTHY", "snapshots": 0, "closing_proxies": 0, "errors": []}
        from .automation import QUICK_SPORTS

        try:
            for sport in QUICK_SPORTS:
                provider = self.provider_factory(sport, api_key=self.api_key)
                cached = self.store.list_records("event_catalog", 1, entity=sport)
                catalog = cached[0]["payload"] if cached else None
                previous = catalog["events"] if catalog else []
                try:
                    if (
                        catalog is None
                        or (now - datetime.fromisoformat(catalog["fetched_at"])).total_seconds()
                        >= 300
                    ):
                        catalog = {"fetched_at": now.isoformat(), "events": provider.list_events()}
                        self.store.append("event_catalog", sport, catalog)
                    # Retain just-started events when an updated provider list drops them.
                    combined = {e["id"]: e for e in previous + catalog["events"]}
                    for event in combined.values():
                        if not self.store.acquire_lease("closing_collector", owner, 600):
                            raise RuntimeError("Collector lease lost")
                        start = datetime.fromisoformat(
                            event["commence_time"].replace("Z", "+00:00")
                        )
                        if start.tzinfo is None:
                            raise ValueError("Event start lacks timezone")
                        seconds = (start - now).total_seconds()
                        if -600 <= seconds <= 0:
                            report["closing_proxies"] += finalize_closing(
                                self.store, event["id"], start, now=now
                            )
                        elif 5 <= seconds <= 90:
                            slot = "90s" if seconds > 30 else "30s"
                            key = digest(["closing_request", event["id"], start.isoformat(), slot])
                            if not reserve_request(self.store, 3, key=key, now=now):
                                continue
                            batch = provider.fetch_event(event["id"], ("h2h", "spreads", "totals"))
                            self.store.archive_batch(batch)
                            report["snapshots"] += 1
                except Exception as exc:
                    report["errors"].append(sport + ":" + type(exc).__name__)
            if report["errors"]:
                report["status"] = "DATA_UNHEALTHY"
            self.store.append(
                "collector_run", "closing", {**report, "completed_at": now.isoformat()}
            )
            return report
        finally:
            self.store.release_lease("closing_collector", owner)
