"""Fail-closed NBA/NHL joint calibration evidence review.

Consumes *genuine* archived, frozen ticket forecasts and resolved results.
Does not fit a model, create synthetic observations or grant betting approval.
Market baselines must be independently archived for the same exact ticket.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite, log
import re

SPORTS = frozenset({"basketball_nba", "icehockey_nhl"})
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
REQUIRED = (
    "sport", "event_id", "ticket_id", "model_version", "split",
    "probability", "outcome", "predicted_at", "forecast_frozen_at",
    "starts_at", "result_observed_at", "features_available_at",
    "trained_through", "test_start", "prospective_start",
    "forecast_snapshot_sha256", "result_snapshot_sha256",
    "market_snapshot_sha256", "market_probability", "market_observed_at",
)


def _utc(value, name):
    if not isinstance(value, str):
        raise ValueError(f"Missing {name}")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid {name}") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"Non-timezone-aware {name}")
    return result.astimezone(UTC)


def _prob(value, name):
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        p = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {name}") from None
    if not isfinite(p) or not 0 < p < 1:
        raise ValueError(f"Invalid {name}")
    return p


def _mean_weighted_by_event(rows, extractor):
    events = defaultdict(list)
    for record in rows:
        events[record["event_id"]].append(extractor(record))
    return sum(sum(values) / len(values) for values in events.values()) / len(events)


def _metrics(rows, key):
    brier = _mean_weighted_by_event(rows, lambda r: (r[key] - r["outcome"]) ** 2)
    logloss = _mean_weighted_by_event(
        rows, lambda r: -(
            r["outcome"] * log(r[key])
            + (1 - r["outcome"]) * log(1 - r[key])
        ),
    )
    return {
        "event_weighted_brier": brier,
        "event_weighted_log_loss": logloss,
    }


def audit_frozen_joint_evidence(rows, *, minimum_events=200, max_quote_age_seconds=600):
    """Evaluate pregame proof and event-weighted Brier/log loss.

    Every row is one real, independently archived exact-ticket forecast,
    plus its settled outcome and a pregame *combined-ticket* market baseline.
    Test and prospective partitions must have disjoint events and the same
    model/version/training cutoff. Multiple tickets from one game count as
    ONE independent event. No numeric metric self-promotes a model.
    """
    if not isinstance(minimum_events, int) or minimum_events < 1:
        raise ValueError("Invalid minimum independent-event sample")
    if not isinstance(max_quote_age_seconds, int) or max_quote_age_seconds <= 0:
        raise ValueError("Invalid market quote age")
    group_rows = defaultdict(list)
    seen = set()
    partition_by_event = {}
    outcomes = {}
    cutoffs = {}
    counts = 0
    for raw in rows:
        counts += 1
        if not isinstance(raw, dict):
            raise ValueError("Invalid evidence row")
        if any(field not in raw for field in REQUIRED):
            raise ValueError("Required forecast/settlement/market provenance missing")
        sport = raw["sport"]
        if sport not in SPORTS:
            raise ValueError("Only NBA/NHL joint-player evidence supported")
        split = raw["split"]
        if split not in {"test", "prospective"}:
            raise ValueError("Only independent test and prospective evidence supported")
        for name in ("event_id", "ticket_id", "model_version"):
            if not isinstance(raw[name], str) or not raw[name].strip():
                raise ValueError("Missing prediction identity")
        for name in ("forecast_snapshot_sha256", "result_snapshot_sha256",
                     "market_snapshot_sha256"):
            if not isinstance(raw[name], str) or not SHA256.fullmatch(raw[name]):
                raise ValueError("Missing immutable snapshot checksum")
        if raw.get("market_baseline_kind") != "independently_quoted_combined_ticket":
            raise ValueError("Independent exact-ticket market baseline required")
        if type(raw["outcome"]) is not int or raw["outcome"] not in (0, 1):
            raise ValueError("Binary resolved settlement required")
        prob = _prob(raw["probability"], "joint probability")
        market = _prob(raw["market_probability"], "combined-ticket market probability")
        pred = _utc(raw["predicted_at"], "predicted_at")
        frozen = _utc(raw["forecast_frozen_at"], "forecast_frozen_at")
        start = _utc(raw["starts_at"], "starts_at")
        settled = _utc(raw["result_observed_at"], "result_observed_at")
        features = _utc(raw["features_available_at"], "features_available_at")
        trained = _utc(raw["trained_through"], "trained_through")
        test_start = _utc(raw["test_start"], "test_start")
        prospective_start = _utc(raw["prospective_start"], "prospective_start")
        quote_time = _utc(raw["market_observed_at"], "market_observed_at")
        if not (trained < test_start < prospective_start):
            raise ValueError("Invalid chronological train/test/prospective boundaries")
        if not (features <= pred <= frozen < start <= settled):
            raise ValueError("Evidence was not frozen point-in-time before the event")
        if not (quote_time <= pred and 0 <= (pred - quote_time).total_seconds()
                <= max_quote_age_seconds):
            raise ValueError("Market baseline is stale or post-prediction")
        if split == "test" and not test_start <= start < prospective_start:
            raise ValueError("Test observation outside frozen evaluation window")
        if split == "prospective" and start < prospective_start:
            raise ValueError("Prospective observation predates prospective boundary")
        group = (sport, raw["model_version"])
        bounds = (trained, test_start, prospective_start)
        if group in cutoffs and cutoffs[group] != bounds:
            raise ValueError("Model version reused with inconsistent training cutoff")
        cutoffs[group] = bounds
        game = (sport, raw["event_id"])
        if game in partition_by_event and partition_by_event[game] != split:
            raise ValueError("Event leaked between test and prospective")
        partition_by_event[game] = split
        ticket = (sport, raw["event_id"], raw["ticket_id"])
        if ticket in outcomes and outcomes[ticket] != raw["outcome"]:
            raise ValueError("Contradictory settled ticket outcome")
        outcomes[ticket] = raw["outcome"]
        unique = (*ticket, raw["model_version"])
        if unique in seen:
            raise ValueError("Duplicate frozen ticket forecast")
        seen.add(unique)
        group_rows[(*group, split)].append({
            "event_id": raw["event_id"], "probability": prob,
            "market_probability": market, "outcome": raw["outcome"],
        })
    reports = []
    groups = sorted({(sport, version) for sport, version, _ in group_rows})
    for sport, version in groups:
        for split in ("test", "prospective"):
            sample = group_rows.get((sport, version, split), [])
            games = len({x["event_id"] for x in sample})
            if not sample:
                reports.append({
                    "sport": sport, "model_version": version, "split": split,
                    "tickets": 0, "independent_events": 0,
                    "status": "MISSING_EVIDENCE", "approved_for_betting": False,
                })
                continue
            model = _metrics(sample, "probability")
            baseline = _metrics(sample, "market_probability")
            mean_p = _mean_weighted_by_event(sample, lambda x: x["probability"])
            realized = _mean_weighted_by_event(sample, lambda x: x["outcome"])
            reports.append({
                "sport": sport, "model_version": version, "split": split,
                "tickets": len(sample), "independent_events": games,
                "model": model, "market_baseline": baseline,
                "brier_improvement": baseline["event_weighted_brier"] - model["event_weighted_brier"],
                "log_loss_improvement": baseline["event_weighted_log_loss"] - model["event_weighted_log_loss"],
                "calibration_gap": abs(mean_p - realized),
                "status": "INSUFFICIENT_INDEPENDENT_EVENTS" if games < minimum_events
                    else "REQUIRES_PROSPECTIVE_EXPERT_REVIEW",
                "approved_for_betting": False,
            })
    return {
        "sport_groups": len(groups),
        "observations_reviewed": counts,
        "reports": reports,
        "all_requested_sports_verified": set(sport for sport, _ in groups) == SPORTS,
        "approved_for_betting": False,
        "notice": "Metrics and declared checksums do not authenticate external archives or approve betting.",
    }
