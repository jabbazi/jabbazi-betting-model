"""Private reviewed-input registration, collection and prospective capture.

This module never declares a provider identity true from a name match. Operators
must supply independently reviewed manifests. Forecasts remain research-only;
settlements and model promotion still use the existing independent gates.
"""
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from .boost_goat_model_map import GOAT_TO_JABBAZI
from .boost_identity_manifest import audit_identity_manifest
from .boost_scope import SPORTS
from .domain.shopping import PriceCard
from .persistence.store import Store, digest, events


def stamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at.astimezone(UTC) if at.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def register_reviewed_manifest(store, sport, records, *, now=None, commit=False):
    """Audit existing attestations; do not add approvals or repair fingerprints."""
    now = now or datetime.now(UTC)
    audit = audit_identity_manifest(sport, records, observed_at=now)
    canonical = all(isinstance(r, dict) and isinstance(r.get("canonical_event_id"), str)
                    and r["canonical_event_id"].strip() for r in records)
    complete = bool(records) and canonical and not audit["rejections"] and (
        audit["unique_structurally_valid_crosswalks"] == len(records))
    result = {**audit, "manifest_sha256": digest(records), "committed": False,
              "registration_allowed": complete,
              "reason": None if complete else "REVIEWED_MANIFEST_INVALID_OR_EMPTY"}
    if commit:
        if not complete or not isinstance(store, Store):
            raise ValueError("A valid reviewed manifest and durable Store are required")
        result["committed"] = bool(store.append(
            "paid_player_identity_manifest", sport,
            {"sport": sport, "records": records, "registered_at": now.isoformat(),
             "manifest_sha256": result["manifest_sha256"], "betting_enabled": False},
            digest(["paid_player_identity_manifest", sport, result["manifest_sha256"]]),
        ))
    return result


def feature_inventory(store, sport, crosswalks, *, limit=10001):
    """Read only relevant events, not the entire historic feature archive."""
    event_ids = sorted({r.get("canonical_event_id") for r in crosswalks
                        if isinstance(r, dict) and isinstance(r.get("canonical_event_id"), str)})
    if not event_ids:
        return []
    if len(event_ids) > 25:
        raise ValueError("Current manifest spans too many games")
    if not isinstance(store, Store):
        return store.list_records("player_feature_snapshot", limit)
    with store.engine.connect() as conn:
        rows = conn.execute(select(events.c.payload).where(
            events.c.kind == "player_feature_snapshot",
            events.c.payload["sport"].as_string() == SPORTS[sport],
            events.c.payload["event_id"].as_string().in_(event_ids),
        ).order_by(events.c.occurred_at.desc(), events.c.id.desc()).limit(limit)).scalars()
        return [{"payload": row} for row in rows]


def matching_game_crosswalks(sport, crosswalks, games):
    """Reject a reviewed map if the actual provider kickoff has since changed."""
    field = {"NBA": "datetime", "NFL": "date", "NHL": "start_time_utc"}[sport]
    by_game = {g["id"]: stamp(g.get(field)) for g in games}
    accepted, rejected = [], 0
    for row in crosswalks:
        if (isinstance(row, dict) and row.get("bdl_game_id") in by_game
                and by_game[row["bdl_game_id"]] is not None
                and stamp(row.get("event_starts_at")) == by_game[row["bdl_game_id"]]):
            accepted.append(row)
        else:
            rejected += 1
    return accepted, rejected


def refresh_reviewed_features(store, sport, offers, crosswalks, snapshots, collector, *,
                              now, deadline, clock, renew, max_contexts=64):
    """Reuse existing real feature collectors for missing, reviewed contexts.

    A manifest must carry the independently reviewed source name and canonical
    matchup before it may initiate a lookup. The resulting source player ID is
    checked again by exact-line inference; name-only success never approves it.
    """
    result = {"attempted_contexts": 0, "archived_snapshots": 0, "rejections": {}}
    reasons = Counter()
    if collector is None:
        result["rejections"] = {"FEATURE_COLLECTOR_UNAVAILABLE": 1}
        return result
    audit = audit_identity_manifest(sport, crosswalks, observed_at=now)
    if audit["rejections"]:
        result["rejections"] = {"REVIEWED_MANIFEST_INVALID": 1}
        return result
    mapping = {(r["bdl_game_id"], r["bdl_player_id"]): r for r in crosswalks}
    existing = {(r.get("event_id"), str(r.get("player_id")), r.get("market")) for r in snapshots}
    seen, contexts = set(), []
    for wrapped in offers:
        raw = wrapped["raw"]
        market = GOAT_TO_JABBAZI[sport].get(raw.get("prop_type"))
        reviewed = mapping.get((raw["game_id"], raw["player_id"]))
        if not reviewed or market is None:
            continue
        key = (reviewed.get("canonical_event_id"), reviewed["source_player_id"], market)
        if key in existing or key in seen:
            continue
        seen.add(key)
        name, event = reviewed.get("source_player_name"), reviewed.get("canonical_event_name")
        if not isinstance(name, str) or not name.strip() or not isinstance(event, str) or " @ " not in event:
            reasons["REVIEWED_FEATURE_LOOKUP_CONTEXT_MISSING"] += 1
            continue
        start = stamp(reviewed.get("event_starts_at"))
        if start is None or start <= now:
            reasons["FEATURE_GAME_ALREADY_STARTED"] += 1
            continue
        contexts.append(SimpleNamespace(
            sport=SPORTS[sport], event_id=key[0], participant=name.strip(),
            market=market, event=event, starts_at=start, in_play=False,
        ))
    if len(contexts) > max_contexts:
        reasons["FEATURE_CONTEXT_LIMIT_REACHED"] += len(contexts) - max_contexts
    for card in contexts[:max_contexts]:
        # Existing collectors have socket budgets. Do not start a new lookup
        # close to the scanner deadline; no budget cap is silently disabled.
        if clock() + 45 >= deadline:
            reasons["FEATURE_TIME_BUDGET_EXHAUSTED"] += 1
            break
        if not renew():
            reasons["SCANNER_LEASE_LOST"] += 1
            break
        result["attempted_contexts"] += 1
        try:
            result["archived_snapshots"] += int(collector.sync(store, [card]) or 0)
        except (ValueError, TypeError, KeyError, OSError):
            reasons["FEATURE_COLLECTION_FAILED"] += 1
    result["rejections"] = dict(reasons)
    return result


def freeze_two_sided_forecasts(store, rows, offers, snapshots, *, now):
    """Freeze real half-line O/U forecasts using an exact two-sided book baseline.

    Single-sided milestones lack a no-vig baseline; do not fabricate one or pass
    their Yes label into the legacy binary-outcome grader. Their immutable paid
    research record is retained separately. No results or wins are invented.
    """
    from .research.player_prospective import freeze_player_candidate
    result = {"frozen": 0, "not_frozen": 0, "baseline_required": "SAME_BOOK_TWO_SIDED_NO_VIG"}
    if not isinstance(store, Store):
        return {**result, "reason": "DURABLE_STORE_REQUIRED"}
    features = {r["snapshot_id"]: r for r in snapshots}
    prices = {}
    for wrapped in offers:
        raw = wrapped["raw"]
        market = raw.get("market", {})
        if market.get("type") != "over_under":
            continue
        try:
            over, under = market["over_odds"], market["under_odds"]
            if any(type(x) is not int or not (x <= -100 or x >= 100) for x in (over, under)):
                continue
            imp = [Decimal(1) / (Decimal(1) + (Decimal(x) / 100 if x > 0 else Decimal(100) / -x)) for x in (over, under)]
            key = (raw["game_id"], raw["player_id"], raw["vendor"], str(raw["line_value"]), raw["prop_type"])
            prices[key] = {"over": imp[0] / sum(imp), "under": imp[1] / sum(imp)}
        except (KeyError, TypeError, ArithmeticError):
            continue
    for row in rows:
        snapshot = features.get(row.get("feature_snapshot_id"))
        sport = next((name for name, code in SPORTS.items() if code == row["sport"]), None)
        source_market = next((name for name, market in GOAT_TO_JABBAZI.get(sport, {}).items() if market == row["market"]), None)
        key = (row["provider_game_id"], row["provider_player_id"], row["best_sportsbook"], str(row["line"]), source_market)
        baseline = prices.get(key, {}).get(row["selection"])
        if not snapshot or baseline is None or row.get("settlement") != "OVER_UNDER":
            result["not_frozen"] += 1
            continue
        card = PriceCard(
            sport=row["sport"], event_id=row["event_id"], event=row.get("event", ""),
            market=row["market"], participant=row["participant"], selection=row["selection"],
            line=Decimal(row["line"]), book_prices={row["best_sportsbook"]: Decimal(str(row["best_decimal"]))},
            best_book=row["best_sportsbook"], best_decimal=Decimal(str(row["best_decimal"])),
            consensus_probability=baseline, market_relative_ev=Decimal(0), sportsbook_disagreement=Decimal(0),
            stale=False, in_play=False, quote_ids=(digest([key, row["source_timestamp"]]),),
            observed_at=now, source_timestamp=stamp(row["source_timestamp"]), starts_at=stamp(row["starts_at"]),
            executable=False,
        )
        estimate = SimpleNamespace(probability=Decimal(str(row["model_probability"])),
                                   model_version=row["model_version"], feature_snapshot=snapshot)
        try:
            frozen = freeze_player_candidate(store, card, estimate,
                {"model_stage": row["model_stage"], "model_can_influence_cash": False,
                 "market_baseline_basis": "SAME_BOOK_TWO_SIDED_NO_VIG", "joint_probability_verified": False}, now=now)
            result["frozen"] += int(bool(frozen))
            result["not_frozen"] += int(not frozen)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            result["not_frozen"] += 1
    return result
