"""Offline NFL efficiency / MLB starter features from archived observations.

Never backdate a modern download to the date a game happened. Revisions are
selected by when this system first observed that exact payload, not event date.
This module does not train a model, generate probabilities, or change live scans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from jabazi.research.prop_data import timestamp

SCHEMA = "advanced-context-0.1.0"
KINDS = {
    "nfl_team": "americanfootball_nfl",
    "mlb_pitcher": "baseball_mlb",
    "mlb_starter": "baseball_mlb",
}
NFL_FIELDS = {
    "offense_plays",
    "offense_epa",
    "offense_successes",
    "defense_plays",
    "defense_epa_allowed",
    "defense_successes_allowed",
}
MLB_FIELDS = {"outs", "batters_faced", "strikeouts", "walks", "earned_runs", "pitches", "started"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Finite numeric statistic required")
    return value


def identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty canonical identity required")
    return value


def known_at(row):
    observed = timestamp(row["observed_at"])
    # Some providers stamp a record before it is actually delivered to us.
    return max(observed, timestamp(row["published_at"])) if row.get("published_at") else observed


def validate_stat(row):
    start, end = timestamp(row["starts_at"]), timestamp(row["ended_at"])
    if not start < end <= timestamp(row["observed_at"]):
        raise ValueError("Completed statistic must be observed after the game ended")
    values = row["values"]
    if row["status"] == "void":
        if values:
            raise ValueError("Voided statistic must not carry values")
        return
    if row["status"] != "final":
        raise ValueError("Only final or explicitly voided statistics are admitted")
    fields = NFL_FIELDS if row["kind"] == "nfl_team" else MLB_FIELDS
    if set(values) != fields:
        raise ValueError("Statistic schema mismatch")
    for key, value in values.items():
        number(value)
        if "epa" not in key and (value < 0 or int(value) != value):
            raise ValueError("Counts must be nonnegative integers")
    if row["kind"] == "nfl_team":
        for side in ("offense", "defense"):
            success = side + ("_successes" if side == "offense" else "_successes_allowed")
            if not 0 <= values[success] <= values[side + "_plays"] or values[side + "_plays"] == 0:
                raise ValueError("Invalid success count or empty team coverage")
    elif (
        values["started"] not in (0, 1)
        or values["batters_faced"] == 0
        or values["strikeouts"] + values["walks"] > values["batters_faced"]
    ):
        raise ValueError("Inconsistent pitching counts")


class AdvancedContext:
    """Provider-neutral, one canonical ID namespace per input document.

    Evidence references record provenance supplied by an ingestion process;
    they cannot independently prove an archive timestamp or licensing rights.
    """

    def __init__(self, document):
        # Detach from caller mutation, also reject non-JSON/nonfinite payloads.
        document = json.loads(json.dumps(document, allow_nan=False))
        manifest = document["manifest"]
        if manifest.get("data_mode") != "real" or manifest.get("schema") != SCHEMA:
            raise ValueError("Real, schema-versioned data required")
        for key in ("provider", "id_namespace", "research_rights_reference"):
            identity(manifest.get(key))
        self.manifest, self.source_checksum = manifest, digest(document)
        self.index = defaultdict(list)
        seen, revisions = set(), set()
        for row in document["snapshots"]:
            sid = identity(row["snapshot_id"])
            kind = row["kind"]
            if sid in seen or kind not in KINDS:
                raise ValueError("Duplicate snapshot ID or unsupported snapshot kind")
            seen.add(sid)
            if not re.fullmatch(r"[0-9a-f]{64}", row["raw_sha256"]):
                raise ValueError("Raw source SHA256 required")
            for key in ("event_id", "entity_id", "archive_reference"):
                identity(row[key])
            timestamp(row["starts_at"])
            when = known_at(row)
            key = (kind, row["event_id"], row["entity_id"])
            revision = (*key, when)
            if revision in revisions:
                raise ValueError("Ambiguous revision at identical availability timestamp")
            revisions.add(revision)
            if kind == "mlb_starter":
                if not timestamp(row["observed_at"]) < timestamp(row["starts_at"]):
                    raise ValueError("Starter announcement must be captured before first pitch")
                if row["status"] not in {"probable", "confirmed", "scratched", "unknown"}:
                    raise ValueError("Unknown starter status")
                if row["status"] in {"probable", "confirmed"}:
                    identity(row["pitcher_id"])
                elif row.get("pitcher_id") is not None:
                    raise ValueError("Unavailable starter must have null pitcher identity")
            else:
                validate_stat(row)
            self.index[key].append(row)
        for versions in self.index.values():
            versions.sort(key=known_at)

    def _latest(self, kind, entity, decision):
        output = []
        for (k, _, e), versions in self.index.items():
            if (k, e) != (kind, entity):
                continue
            eligible = [r for r in versions if known_at(r) <= decision]
            if eligible:
                output.append(eligible[-1])
        return output

    def build(
        self, request, *, window=8, minimum_games=4, lookback_days=370, starter_max_age_hours=6
    ):
        if (
            any(type(v) is not int or v < 1 for v in (window, minimum_games, lookback_days))
            or minimum_games > window
            or number(starter_max_age_hours) <= 0
        ):
            raise ValueError("Invalid feature policy")
        event, home, away = (identity(request[k]) for k in ("event_id", "home_id", "away_id"))
        start, decision = timestamp(request["starts_at"]), timestamp(request["prediction_at"])
        sport = request["sport"]
        if home == away or not decision < start or sport not in set(KINDS.values()):
            raise ValueError("Invalid pregame feature request")
        features, used, reasons = {}, [], []
        counts = {}
        for side, team in (("home", home), ("away", away)):
            entity, kind = team, "nfl_team"
            if sport == "baseball_mlb":
                choices = [
                    r for r in self._latest("mlb_starter", team, decision) if r["event_id"] == event
                ]
                starter = choices[0] if choices else None
                if starter is None:
                    reasons.append(f"{side}: missing archived starter announcement")
                    continue
                used.append(starter)
                if (
                    starter["status"] != "confirmed"
                    or timestamp(starter["starts_at"]) != start
                    or decision - timestamp(starter["observed_at"])
                    > timedelta(hours=starter_max_age_hours)
                ):
                    reasons.append(f"{side}: starter unconfirmed, changed, or stale")
                    continue
                entity, kind = starter["pitcher_id"], "mlb_pitcher"
            history = [
                r
                for r in self._latest(kind, entity, decision)
                if r["event_id"] != event
                and r["status"] == "final"
                and decision - timedelta(days=lookback_days) <= timestamp(r["ended_at"]) <= decision
                and (kind != "mlb_pitcher" or r["values"]["started"] == 1)
            ]
            history.sort(key=lambda r: (timestamp(r["starts_at"]), r["event_id"]))
            history = history[-window:]
            counts[side] = len(history)
            if len(history) < minimum_games:
                reasons.append(f"{side}: insufficient archived prior games")
                continue
            used.extend(history)
            totals = {key: sum(r["values"][key] for r in history) for key in history[0]["values"]}
            if kind == "nfl_team":
                values = {
                    "offense_epa_per_play": totals["offense_epa"] / totals["offense_plays"],
                    "offense_success_rate": totals["offense_successes"] / totals["offense_plays"],
                    "defense_epa_allowed_per_play": totals["defense_epa_allowed"]
                    / totals["defense_plays"],
                    "defense_success_rate_allowed": totals["defense_successes_allowed"]
                    / totals["defense_plays"],
                }
            else:
                if totals["outs"] == 0:
                    reasons.append(f"{side}: no prior pitching outs")
                    continue
                values = {
                    "starter_k_rate": totals["strikeouts"] / totals["batters_faced"],
                    "starter_bb_rate": totals["walks"] / totals["batters_faced"],
                    "starter_era": 27 * totals["earned_runs"] / totals["outs"],
                    "starter_outs_per_start": totals["outs"] / len(history),
                    "starter_pitches_per_start": totals["pitches"] / len(history),
                    "starter_rest_days": (
                        start - timestamp(history[-1]["starts_at"])
                    ).total_seconds()
                    / 86400,
                }
            features.update({f"{side}_{key}": value for key, value in values.items()})
        used = sorted({r["snapshot_id"]: r for r in used}.values(), key=lambda r: r["snapshot_id"])
        policy = {
            "window": window,
            "minimum_games": minimum_games,
            "lookback_days": lookback_days,
            "starter_max_age_hours": starter_max_age_hours,
        }
        return {
            "schema": SCHEMA,
            "event_id": event,
            "sport": sport,
            "prediction_at": decision.isoformat(),
            "starts_at": start.isoformat(),
            "status": "INSUFFICIENT_DATA" if reasons else "FEATURES_AVAILABLE",
            "features": None if reasons else features,
            "reasons": reasons,
            "history_counts": counts,
            "policy": policy,
            "approved_for_betting": False,
            "model_probability": None,
            "source_checksum": self.source_checksum,
            "feature_version": digest(
                {
                    "schema": SCHEMA,
                    "policy": policy,
                    "manifest": self.manifest,
                    "request": request,
                    "snapshots": used,
                }
            ),
            "used_snapshots": [
                {
                    k: r.get(k)
                    for k in (
                        "snapshot_id",
                        "event_id",
                        "entity_id",
                        "raw_sha256",
                        "archive_reference",
                        "observed_at",
                        "published_at",
                    )
                }
                for r in used
            ],
            "provider": self.manifest["provider"],
            "id_namespace": self.manifest["id_namespace"],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    context = AdvancedContext(json.loads(args.snapshots.read_text()))
    requests = json.loads(args.requests.read_text())
    if not isinstance(requests, list):
        raise ValueError("Requests must be an array")
    keys = [(r["sport"], r["event_id"], r["prediction_at"]) for r in requests]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate event/prediction request")
    results = [context.build(r) for r in requests]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"schema": SCHEMA, "results": results}, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "requests": len(results),
                "features_available": sum(r["features"] is not None for r in results),
                "approved_for_betting": False,
            }
        )
    )


if __name__ == "__main__":
    main()
