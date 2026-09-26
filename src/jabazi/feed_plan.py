"""Budgeted game and NFL/MLB event-market ingestion; no probability fabrication."""

import json
import os
from datetime import UTC, datetime

EVENT_MARKETS = {
    "americanfootball_nfl": (
        "player_pass_yds",
        "player_reception_yds",
        "player_rush_yds",
        "player_receptions",
        "player_pass_tds",
        "player_anytime_td",
        "player_pass_attempts",
        "player_pass_completions",
        "player_rush_attempts",
        "alternate_spreads",
        "alternate_totals",
        "team_totals",
    ),
    "baseball_mlb": (
        "pitcher_strikeouts",
        "batter_hits",
        "batter_total_bases",
        "pitcher_outs",
        "batter_home_runs",
        "batter_rbis",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "batter_runs_scored",
        "alternate_spreads",
        "alternate_totals",
        "team_totals",
    ),
}
PRIMARY = (*EVENT_MARKETS, "americanfootball_ncaaf")


class FeedPlan:
    def __init__(self, factory, store, budget, reserve, errors, renew, *, now=None, player_models=None):
        self.factory, self.store = factory, store
        self.player_models = player_models or {}
        self.budget, self.reserve, self.errors, self.renew = budget, reserve, errors, renew
        self.now = now or datetime.now(UTC)
        self.spent, self.remaining, self.stopped = 0, None, False
        self.coverage = {
            "event_odds_enabled": os.getenv("JABBAZI_EVENT_ODDS_ENABLED", "true").lower() == "true",
            "sports": {},
        }
        self.per_event = int(os.getenv("JABBAZI_EVENT_MARKETS_PER_EVENT", "3"))
        self.max_events = int(os.getenv("JABBAZI_EVENT_MAX_EVENTS_PER_RUN", "4"))
        if not 1 <= self.per_event <= 12 or not 0 <= self.max_events <= 100:
            raise ValueError("Invalid event-market scan limits")

    def fetch(self, sport, markets, event=None):
        cost = len(markets)  # Configured adapter permits at most ten distinct books.
        if self.stopped or self.spent + cost > self.budget:
            return None
        if self.remaining is not None and self.remaining - cost < self.reserve:
            self.coverage["stop_reason"] = "PROVIDER_CREDIT_RESERVE"
            self.stopped = True
            return None
        if not self.renew():
            raise RuntimeError("Scanner lease could not be renewed")
        if self.store is not None:
            from .operations import reserve_request

            if not reserve_request(self.store, cost):
                self.errors.append("MONTHLY_QUOTA_LIMIT")
                self.coverage["stop_reason"] = "MONTHLY_QUOTA_LIMIT"
                self.stopped = True
                return None
        self.spent += cost
        if event and self.store is not None:
            self.store.append(
                "event_market_request",
                event["id"],
                {
                    "sport": sport,
                    "event_id": event["id"],
                    "markets": list(markets),
                    "requested_at": self.now.isoformat(),
                    "reserved_credits": cost,
                },
            )
        try:
            provider = self.factory(sport, markets)
            batch = provider.fetch_event(event["id"], markets) if event else provider.fetch()
            self.remaining = batch.requests_remaining
            return batch
        except Exception as exc:
            self.errors.append(f"{sport}:{'event_odds_' if event else ''}{type(exc).__name__}")
            return None

    def batches(self, selected):
        candidates = {sport: [] for sport in EVENT_MARKETS}
        primary = [s for s in selected if s["key"] in PRIMARY]
        other = [s for s in selected if s["key"] not in PRIMARY]
        for sport in primary:
            batch = self.fetch(sport["key"], ("h2h", "spreads", "totals"))
            if batch is None:
                continue
            yield sport, batch
            if sport["key"] in candidates:
                try:
                    raw = json.loads(batch.raw_payload)
                except (ValueError, TypeError):
                    self.errors.append(f"{sport['key']}:event_catalog_invalid")
                    continue
                for event in raw if isinstance(raw, list) else []:
                    try:
                        start = datetime.fromisoformat(
                            event["commence_time"].replace("Z", "+00:00")
                        )
                        horizon = 7 * 86400 if sport["key"] == "americanfootball_nfl" else 36 * 3600
                        if (
                            event.get("id")
                            and event.get("bookmakers")
                            and 0 < (start - self.now).total_seconds() <= horizon
                        ):
                            candidates[sport["key"]].append(event)
                    except (AttributeError, KeyError, TypeError, ValueError):
                        continue
        prior = self.store.list_records("event_market_request", 1000) if self.store else []
        history = {}
        for record in prior:
            p = record["payload"]
            history.setdefault((p["sport"], p["event_id"]), []).append(p)
        for sport, events in candidates.items():
            events.sort(
                key=lambda e: (
                    max((p["requested_at"] for p in history.get((sport, e["id"]), [])), default=""),
                    e["commence_time"],
                    e["id"],
                )
            )
            sport_models = {
                market: model
                for (model_sport, market), model in self.player_models.items()
                if model_sport == sport
            }
            stages = {getattr(model, "stage", "SHADOW_ONLY") for model in sport_models.values()}
            player_status = (
                "PRODUCTION_APPROVED"
                if stages == {"PRODUCTION_APPROVED"} and stages
                else "LIMITED_LIVE"
                if "PRODUCTION_APPROVED" in stages or "LIMITED_LIVE" in stages
                else "VALIDATING"
                if "VALIDATING" in stages
                else "SHADOW_ONLY"
                if stages
                else "UNAVAILABLE"
            )
            self.coverage["sports"][sport] = {
                "eligible_events": len(events),
                "requested_events": 0,
                "requests": [],
                "player_model_status": player_status,
                "player_model_markets": {
                    market: getattr(model, "stage", "SHADOW_ONLY")
                    for market, model in sorted(sport_models.items())
                },
                "partial": bool(events),
            }
        requests = 0
        if self.coverage["event_odds_enabled"]:
            # Round robin avoids spending the whole event budget on one league.
            while any(candidates.values()) and requests < self.max_events and not self.stopped:
                progressed = False
                for sport, events in candidates.items():
                    if not events or requests >= self.max_events:
                        continue
                    available = min(self.per_event, self.budget - self.spent)
                    if available <= 0:
                        break
                    event = events.pop(0)
                    # Rotate market bundles per event using audited requests, not random selection.
                    all_markets = EVENT_MARKETS[sport]
                    offset = sum(
                        len(p["markets"]) for p in history.get((sport, event["id"]), [])
                    ) % len(all_markets)
                    markets = tuple(
                        all_markets[(offset + i) % len(all_markets)] for i in range(available)
                    )
                    before = self.spent
                    batch = self.fetch(sport, markets, event)
                    if self.spent == before:
                        continue
                    progressed = True
                    requests += 1
                    report = self.coverage["sports"][sport]
                    report["requested_events"] += 1
                    report["requests"].append(
                        {
                            "event_id": event["id"],
                            "markets": list(markets),
                            "quotes": len(batch.quotes) if batch else 0,
                            "status": "RECEIVED" if batch else "UNAVAILABLE",
                        }
                    )
                    if batch is not None:
                        yield {"key": sport}, batch
                if not progressed:
                    break
        # A scan requests only a bounded subset of event/market combinations.
        for report in self.coverage["sports"].values():
            report["partial"] = bool(report["eligible_events"])
        self.coverage["event_requests"] = requests
        for sport in other:
            markets = ("outrights",) if sport.get("has_outrights") else ("h2h", "spreads", "totals")
            batch = self.fetch(sport["key"], markets)
            if batch is not None:
                yield sport, batch
        self.coverage["credits_reserved_this_run"] = self.spent
        self.coverage["note"] = (
            "Partial event/market coverage within existing quota. Player-model stages are reported per sport/market; market probabilities remain separate from model estimates."
        )
