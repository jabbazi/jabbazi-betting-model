"""Immutable V5 market-intelligence receipts and closing-line evaluation."""
from __future__ import annotations

from datetime import UTC, datetime
import math

from jabazi.persistence.store import digest


def snapshot_payload(card, *, observed_at=None):
    observed_at = observed_at or datetime.now(UTC)
    if observed_at.tzinfo is None or card.starts_at is None or observed_at >= card.starts_at:
        raise ValueError("Market snapshot must be pregame and timezone-aware")
    books = {
        str(book): str(decimal)
        for book, decimal in sorted(card.book_prices.items())
        if math.isfinite(float(decimal)) and float(decimal) > 1
    }
    if not books:
        raise ValueError("No executable market prices")
    return {
        "sport": card.sport,
        "event_id": card.event_id,
        "starts_at": card.starts_at.isoformat(),
        "market": card.market,
        "selection": card.selection,
        "participant": card.participant,
        "line": None if card.line is None else str(card.line),
        "observed_at": observed_at.isoformat(),
        "source_timestamp": card.source_timestamp.isoformat(),
        "book_prices": books,
        "best_book": card.best_book,
        "best_decimal": str(card.best_decimal),
        "consensus_no_vig_probability": float(card.consensus_probability),
        "quote_ids": list(card.quote_ids),
    }


def archive_snapshot(store, card, *, observed_at=None):
    payload = snapshot_payload(card, observed_at=observed_at)
    # A source/quote set can be archived once; later price changes create new receipts.
    key = digest([
        "market_snapshot_v1",
        payload["event_id"],
        payload["market"],
        payload["selection"],
        payload["participant"],
        payload["line"],
        payload["source_timestamp"],
        payload["quote_ids"],
    ])
    with store.transaction() as conn:
        return store._append(conn, "market_snapshot", card.event_id, payload, key)


def clv(entry, close):
    """Probability-space and price-space CLV for exact market identity."""
    identity = ("sport", "event_id", "market", "selection", "participant", "line")
    if any(entry.get(k) != close.get(k) for k in identity):
        raise ValueError("CLV identity mismatch")
    entry_at = datetime.fromisoformat(str(entry["observed_at"]).replace("Z", "+00:00"))
    close_at = datetime.fromisoformat(str(close["observed_at"]).replace("Z", "+00:00"))
    if entry_at.tzinfo is None or close_at.tzinfo is None or entry_at >= close_at:
        raise ValueError("Closing snapshot must follow entry snapshot")
    ep = float(entry["consensus_no_vig_probability"])
    cp = float(close["consensus_no_vig_probability"])
    ed = float(entry["best_decimal"])
    cd = float(close["best_decimal"])
    if any(not math.isfinite(v) for v in (ep, cp, ed, cd)) or not 0 < ep < 1 or not 0 < cp < 1:
        raise ValueError("Invalid CLV inputs")
    return {
        "entry_probability": ep,
        "closing_probability": cp,
        # Positive means the market moved toward the selected outcome after entry.
        "clv_probability_points": cp - ep,
        # Positive means the entry obtained a larger decimal return than the close.
        "clv_decimal": ed - cd,
        "entry_decimal": ed,
        "closing_decimal": cd,
        "minutes_between": (close_at - entry_at).total_seconds() / 60,
    }


def movement(snapshots):
    if len(snapshots) < 2:
        return None
    ordered = sorted(snapshots, key=lambda row: row["observed_at"])
    first, last = ordered[0], ordered[-1]
    identity = ("sport", "event_id", "market", "selection", "participant", "line")
    if any(first.get(k) != last.get(k) for k in identity):
        raise ValueError("Movement snapshots are not the same market")
    return {
        "first_probability": float(first["consensus_no_vig_probability"]),
        "last_probability": float(last["consensus_no_vig_probability"]),
        "probability_move": float(last["consensus_no_vig_probability"]) - float(first["consensus_no_vig_probability"]),
        "first_best_decimal": float(first["best_decimal"]),
        "last_best_decimal": float(last["best_decimal"]),
        "sample_count": len(ordered),
        "first_at": first["observed_at"],
        "last_at": last["observed_at"],
    }


def archive_closing_snapshot(store, card):
    """Archive the freshest exact-market pre-start card as closing evidence."""
    if card.starts_at is None or card.observed_at >= card.starts_at:
        raise ValueError("Closing market snapshot must be pre-start")
    payload = snapshot_payload(card, observed_at=card.observed_at)
    payload["closing_evidence"] = True
    key = digest([
        "closing_market_snapshot_v1",
        payload["event_id"],
        payload["market"],
        payload["selection"],
        payload["participant"],
        payload["line"],
        payload["source_timestamp"],
        payload["quote_ids"],
    ])
    with store.transaction() as conn:
        return store._append(
            conn, "closing_market_snapshot", card.event_id, payload, key
        )


def exact_clv_from_store(
    store, *, event_id, market, selection, line, participant, entry_observed_at
):
    """Compare an exact archived entry snapshot with the exact archived close."""
    def matches(row):
        p = row["payload"]
        return (
            p.get("event_id") == event_id
            and p.get("market") == market
            and p.get("selection") == selection
            and p.get("participant") == participant
            and p.get("line") == (None if line is None else str(line))
        )

    entries = [
        row["payload"]
        for row in store.list_records("market_snapshot", 1000, entity=event_id)
        if matches(row) and row["payload"].get("observed_at") == entry_observed_at
    ]
    closes = [
        row["payload"]
        for row in store.list_records("closing_market_snapshot", 1000, entity=event_id)
        if matches(row)
    ]
    if len(entries) != 1 or not closes:
        return {
            "status": "UNAVAILABLE",
            "reason": "Exact entry and closing snapshots are required",
        }
    close = max(closes, key=lambda row: row["observed_at"])
    return {"status": "EXACT_CLV", **clv(entries[0], close)}
