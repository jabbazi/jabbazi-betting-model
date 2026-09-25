"""Fit, persist, and re-evaluate player-prop model artifacts."""
from __future__ import annotations

import json
from pathlib import Path

from jabazi.models.train_player_props import fit_prop_model, promotion_decision
from jabazi.persistence.store import digest
from jabazi.research.player_prospective import validation_report


def fit_and_store(
    store,
    document,
    *,
    train_before,
    test_before,
    minimum_per_split=100,
):
    artifact = fit_prop_model(
        document,
        train_before=train_before,
        test_before=test_before,
        minimum_per_split=minimum_per_split,
    )
    entity = f"{artifact['sport']}|{artifact['market']}"
    store.append(
        "player_prop_model",
        entity,
        artifact,
        digest(["player_prop_model", entity, artifact["model_version"]]),
    )
    return artifact


def fit_file_and_store(
    store,
    source,
    *,
    train_before,
    test_before,
    minimum_per_split=100,
):
    document = json.loads(Path(source).read_text(encoding="utf-8"))
    return fit_and_store(
        store,
        document,
        train_before=train_before,
        test_before=test_before,
        minimum_per_split=minimum_per_split,
    )


def refresh_promotions(store):
    """Persist a new immutable artifact revision only when evidence changes its stage."""
    report = validation_report(store)
    prospective = {
        (row["sport"], row["model_version"], row["market"]): row
        for row in report.get("buckets", [])
    }
    changed = []
    for sport in ("americanfootball_nfl", "baseball_mlb"):
        # Read broadly enough for every currently configured prop market.
        for record in store.list_records("player_prop_model", 500):
            artifact = record["payload"]
            if artifact.get("sport") != sport:
                continue
            key = (sport, artifact.get("model_version"), artifact.get("market"))
            updated = promotion_decision(artifact, prospective.get(key))
            if updated.get("stage") == artifact.get("stage") and (
                updated.get("validation", {}).get("prospective_sample_count")
                == artifact.get("validation", {}).get("prospective_sample_count")
            ):
                continue
            entity = f"{sport}|{artifact['market']}"
            store.append(
                "player_prop_model",
                entity,
                updated,
                digest([
                    "player_prop_promotion",
                    entity,
                    artifact["model_version"],
                    updated.get("stage"),
                    updated.get("validation", {}).get("prospective_sample_count", 0),
                ]),
            )
            changed.append(
                {
                    "sport": sport,
                    "market": artifact["market"],
                    "model_version": artifact["model_version"],
                    "stage": updated["stage"],
                    "approved_for_betting": updated["validation"]["promotion_passed"],
                }
            )
    return changed
