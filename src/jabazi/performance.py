"""Reported ledger outcomes, keeping original settlements and corrections auditable."""

from decimal import Decimal
from sqlalchemy import select
from .persistence.store import events, positions


def report(store):
    with store.engine.connect() as conn:
        rows = list(conn.execute(select(positions)).mappings())
        transitions = list(
            conn.execute(
                select(events)
                .where(events.c.kind == "position_transition")
                .order_by(events.c.occurred_at, events.c.id)
            ).mappings()
        )
    latest = {}
    for event in transitions:
        if event["payload"]["state"] == "settled":
            latest[event["entity"]] = event["payload"]["evidence"]
    groups = {}
    for row in rows:
        p = row["payload"]
        key = (p["sport"], p.get("market", "unrecorded"), p.get("origin", "unknown"))
        g = groups.setdefault(
            key,
            {
                "sport": key[0],
                "market": key[1],
                "origin": key[2],
                "positions": 0,
                "settled": 0,
                "wins": 0,
                "losses": 0,
                "pushes_or_voids": 0,
                "settled_stake": Decimal(0),
                "profit": Decimal(0),
                "profit_units": Decimal(0),
            },
        )
        g["positions"] += 1
        if row["state"] != "settled" or row["id"] not in latest:
            continue
        outcome = latest[row["id"]]
        amount, profit = Decimal(p["stake"]), Decimal(outcome["profit"])
        g["settled"] += 1
        g["settled_stake"] += amount
        g["profit"] += profit
        g["profit_units"] += profit / Decimal(p["unit_size"])
        if outcome.get("result") == "win":
            g["wins"] += 1
        elif outcome.get("result") == "loss":
            g["losses"] += 1
        elif outcome.get("result") in {"push", "void"}:
            g["pushes_or_voids"] += 1
    for g in groups.values():
        g["roi"] = g["profit"] / g["settled_stake"] if g["settled_stake"] else None
        decisive = g["wins"] + g["losses"]
        g["win_rate"] = Decimal(g["wins"]) / decisive if decisive else None
    return {
        "provenance": "OWNER_REPORTED_LEDGER",
        "groups": list(groups.values()),
        "total_positions": len(rows),
        "corrections_retained": True,
        "note": "Owner-reported outcomes, not independently verified sportsbook performance or model backtest. ROI uses all settled stakes, including voids.",
    }
