"""Bounded, source-backed research updates; never official wagers."""
from datetime import UTC, datetime
import math
from zoneinfo import ZoneInfo

from .discord_daily import sport_label
from .discord_content import american


def row_key(row):
    return tuple(str(row.get(k) or "") for k in
                 ("sport", "event_id", "market", "selection", "line", "participant"))


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def observations(snapshots, *, lane, now=None):
    now = now or datetime.now(UTC)
    if lane not in {"research", "market"} or not snapshots:
        return []
    current = snapshots[0]["payload"]
    try:
        age = (now-datetime.fromisoformat(current["completed_at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return []
    if not current.get("healthy") or current.get("truncated") or not 0 <= age <= 900:
        return []
    previous = {}
    if len(snapshots) > 1:
        prior = snapshots[1]["payload"]
        try:
            prior_age = (now-datetime.fromisoformat(prior["completed_at"])).total_seconds()
            if prior.get("healthy") and age < prior_age <= 3600:
                previous = {row_key(row): row for row in prior.get("rows", [])}
        except (KeyError, ValueError, TypeError):
            pass
    updates = []
    for row in current.get("rows", []):
        label = sport_label(row.get("sport", ""))
        if not label or not row.get("event_id") or row.get("in_play"):
            continue
        try:
            if datetime.fromisoformat(row["starts_at_utc"]) <= now:
                continue
            quoted = datetime.fromisoformat(row["price_time_utc"])
            if not 0 <= (now-quoted).total_seconds() <= 300:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        market, model = number(row.get("market_no_vig_probability")), number(row.get("research_probability"))
        old = previous.get(row_key(row), {})
        if market is None or not 0 < market < 1:
            continue
        health = str(row.get("data_health", "UNKNOWN"))
        if lane == "market":
            before = number(old.get("market_no_vig_probability"))
            if before is None or abs(market-before) < 0.03 or row.get("price_stale") or row.get("executable") is not True:
                continue
            priority = abs(market-before)
            description = f"Market no-vig probability: **{before:.1%} → {market:.1%}** ({(market-before)*100:+.1f} percentage points)."
            title = "MARKET WATCH • meaningful move"
        else:
            changed_health = old.get("data_health") not in {None, "UNKNOWN", health}
            disagreement = abs(model-market) if model is not None and 0 < model < 1 else 0
            if disagreement < 0.08 and not changed_health:
                continue
            priority = disagreement + int(changed_health)
            description = (f"Research model **{model:.1%}** vs market no-vig **{market:.1%}**. "
                           if model is not None and 0 < model < 1 else "No supported model probability. ")
            if changed_health:
                description += f"Data health changed: {old['data_health']} → {health}. "
            description += "\n" + str(row.get("reason") or "Review model/market disagreement and uncertainty before considering action.")[:220]
            state = "QUARANTINED" if str(row.get("status")).upper() == "QUARANTINED" else "PRICE CHECK" if row.get("price_stale") or row.get("executable") is not True else "WATCH"
            description += f"\nResearch state: **{state}**. Disagreement can reflect model error; it is not proof of value."
            title = "VIP RESEARCH • NOT A PICK"
        price = number(row.get("decimal_odds"))
        quote = f"{row.get('book')} {american(price):+d}" if price and price > 1 and row.get("book") else "PRICE CHECK"
        stamp = quoted.astimezone(ZoneInfo("America/Chicago")).strftime("%I:%M %p %Z")
        selection = str(row.get("participant") or row.get("selection") or "") + " " + str(row.get("line") or "")
        bucket = now.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H")
        updates.append({"priority": priority,
            "identity": [bucket, row["sport"], row["event_id"], row.get("market"), lane],
            "embed": {"title": title, "color": 0x8B35E8 if lane == "research" else 0x3498DB,
                "description": f"**{label} • {str(row.get('event'))[:180]}**\n{selection.strip()[:150]} • {row.get('market')}\n\n{description}",
                "fields": [{"name": "Best observed price", "value": quote, "inline": True},
                           {"name": "Data health", "value": health, "inline": True},
                           {"name": "As of", "value": stamp, "inline": True}],
                "footer": {"text": "Research snapshot • recheck prices • not an official wager • no stake assigned"}}})
    unique = {}
    for update in sorted(updates, key=lambda item: item["priority"], reverse=True):
        unique.setdefault(tuple(update["identity"]), update)
    return list(unique.values())[:3]
