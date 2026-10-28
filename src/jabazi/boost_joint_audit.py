"""Out-of-sample joint-probability calibration audit.

This is evidence assessment only: no synthetic history, no automatic model
promotion. Each observation is one independent game-level ticket outcome.
"""
from __future__ import annotations

from collections import defaultdict
from math import log


def audit_joint_predictions(rows, *, minimum_events=200):
    """Report Brier/log loss by sport and prevent leakage or duplicate tickets.

    Expected rows: sport, event_id, ticket_id, predicted_at, starts_at,
    probability, outcome (0/1), model_version, split ('test'/'prospective').
    """
    from datetime import datetime
    buckets = defaultdict(list)
    seen = set()
    event_splits = {}
    ticket_outcomes = {}
    for row in rows:
        sport = row["sport"]
        if sport not in {"basketball_nba", "icehockey_nhl"}:
            raise ValueError("Unsupported calibration sport")
        split = row["split"]
        if split not in {"test", "prospective"}:
            raise ValueError("Only out-of-sample evidence admitted")
        p = float(row["probability"])
        from math import isfinite
        if not isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid probability")
        if row["outcome"] not in (0, 1) or isinstance(row["outcome"], bool):
            raise ValueError("Outcome must be binary")
        pred = datetime.fromisoformat(row["predicted_at"].replace("Z", "+00:00"))
        start = datetime.fromisoformat(row["starts_at"].replace("Z", "+00:00"))
        if pred.tzinfo is None or start.tzinfo is None or pred >= start:
            raise ValueError("Invalid point-in-time evidence")
        if any(not isinstance(row.get(field), str) or not row[field].strip()
               for field in ("event_id", "ticket_id", "model_version")):
            raise ValueError("Missing prediction provenance")
        event_key = (sport, row["event_id"])
        previous_split = event_splits.setdefault(event_key, split)
        if previous_split != split:
            raise ValueError("Event overlap between test and prospective splits")
        outcome_key = (sport, row["event_id"], row["ticket_id"])
        previous_outcome = ticket_outcomes.setdefault(outcome_key, row["outcome"])
        if previous_outcome != row["outcome"]:
            raise ValueError("Conflicting ticket outcomes")
        key = (sport, row["event_id"], row["ticket_id"], row["model_version"])
        if key in seen:
            raise ValueError("Duplicate prediction identity")
        seen.add(key)
        buckets[(sport, row["model_version"], split)].append((p, row["outcome"], row["event_id"]))
    reports = []
    for (sport, version, split), values in sorted(buckets.items()):
        count = len(values)
        events = len({event for _, _, event in values})
        brier = sum((p-y)**2 for p,y,_ in values) / count
        eps = 1e-12
        logloss = -sum(y*log(max(eps,p)) + (1-y)*log(max(eps,1-p))
                       for p,y,_ in values) / count
        mean_p = sum(p for p,_,_ in values)/count
        observed = sum(y for _,y,_ in values)/count
        reports.append({
            "sport": sport, "model_version": version, "split": split,
            "tickets": count, "unique_events": events,
            "brier": brier, "log_loss": logloss,
            "mean_prediction": mean_p, "observed_rate": observed,
            "calibration_gap": abs(mean_p-observed),
            "status": "INSUFFICIENT_EVIDENCE" if events < minimum_events
                      else "REQUIRES_BASELINE_AND_PROSPECTIVE_REVIEW",
            "approved_for_betting": False,
        })
    return {"reports": reports, "approved_for_betting": False}
