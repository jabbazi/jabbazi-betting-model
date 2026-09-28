"""Fit research-only NBA player-prop artifacts from a verified normalized history file.

Input JSON:
{
  "provider": "...",
  "source_checksum": "...",
  "research_rights_reference": "...",
  "rows": [...]
}

No artifact is deployed automatically and historical fitting cannot self-promote.
"""
import argparse
import json
from pathlib import Path

from jabazi.models.train_player_props import fit_prop_model
from jabazi.research.nba_player_experiment import MARKETS, build_dataset
from jabazi.research.prop_data import inspect_prop_dataset

TRAIN_BEFORE = "2024-07-01T00:00:00+00:00"
TEST_BEFORE = "2025-07-01T00:00:00+00:00"


def run(source, output):
    payload = json.loads(Path(source).read_text())
    if not isinstance(payload.get("rows"), list):
        raise ValueError("NBA normalized history rows are required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"approved_for_betting": False, "markets": {}}
    for market in sorted(MARKETS):
        document = build_dataset(
            rows=payload["rows"],
            market=market,
            provider=str(payload.get("provider") or ""),
            source_checksum=str(payload.get("source_checksum") or ""),
            research_rights_reference=str(payload.get("research_rights_reference") or ""),
        )
        inspection = inspect_prop_dataset(
            document,
            train_before=TRAIN_BEFORE,
            test_before=TEST_BEFORE,
            minimum_per_split=100,
        )
        row = {"inspection": inspection, "artifact": None}
        if inspection["status"] == "READY_FOR_RESEARCH_FIT":
            artifact = fit_prop_model(
                document,
                train_before=TRAIN_BEFORE,
                test_before=TEST_BEFORE,
                minimum_per_split=100,
            )
            if artifact["stage"] == "PRODUCTION_APPROVED":
                raise ValueError("Historical NBA training must never self-promote")
            (output / f"{market}.json").write_text(json.dumps(artifact, indent=2) + "\n")
            row["artifact"] = {
                "model_version": artifact["model_version"],
                "stage": artifact["stage"],
                "family": artifact["family"],
                "distribution_validation": artifact["distribution_validation"],
                "validation": artifact["validation"],
            }
        report["markets"][market] = row
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    run(args.source, args.output)
