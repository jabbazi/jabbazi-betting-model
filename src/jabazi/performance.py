"""Reported ledger outcomes, keeping original settlements and corrections auditable."""

from decimal import Decimal
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .persistence.store import events, positions


def report(store, *, now=None):
    now = now or datetime.now(UTC)
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
        "official_periods": official_periods(rows, latest, now),
        "note": "Owner-reported outcomes, not independently verified sportsbook performance or model backtest. ROI uses all settled stakes, including voids.",
    }


def official_periods(rows, settlements, now):
    """Settled scanner-origin cohorts by original betting date, Central time."""
    today = now.astimezone(ZoneInfo("America/Chicago")).date()
    starts = {"Today": today, "This week": today-timedelta(days=today.weekday()),
              "This month": today.replace(day=1), "All time": date.min}
    periods = []
    for label, start in starts.items():
        groups = []
        for parlay in (False, True):
            totals = {"kind": "Parlays" if parlay else "Straights", "settled": 0,
                      "wins": 0, "losses": 0, "pushes_or_voids": 0,
                      "profit_units": Decimal(0), "profit": Decimal(0), "settled_stake": Decimal(0)}
            for row in rows:
                p = row["payload"]
                if p.get("origin") != "scanner" or bool(p.get("parlay")) != parlay or row["state"] != "settled" or row["id"] not in settlements:
                    continue
                try:
                    betting_date = date.fromisoformat(p["betting_date"])
                except (KeyError, ValueError, TypeError):
                    continue
                if not start <= betting_date <= today:
                    continue
                outcome = settlements[row["id"]]
                stake, profit, unit = Decimal(p["stake"]), Decimal(outcome["profit"]), Decimal(p["unit_size"])
                if not all(v.is_finite() for v in (stake, profit, unit)) or stake <= 0 or unit <= 0:
                    continue
                totals["settled"] += 1
                totals["settled_stake"] += stake
                totals["profit"] += profit
                totals["profit_units"] += profit/unit
                result_key = {"win": "wins", "loss": "losses", "push": "pushes_or_voids", "void": "pushes_or_voids"}.get(outcome.get("result"))
                if result_key:
                    totals[result_key] += 1
            totals["roi"] = totals["profit"]/totals["settled_stake"] if totals["settled_stake"] else None
            groups.append(totals)
        periods.append({"label": label, "from": start.isoformat(), "through": today.isoformat(), "groups": groups})
    return periods
