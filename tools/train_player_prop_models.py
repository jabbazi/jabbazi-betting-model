"""Fit every admitted NFL/MLB player-prop distribution artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jabazi.models.train_player_props import fit_prop_model


def train_directory(input_dir: Path, output_dir: Path, *, train_before: str, test_before: str):
    output_dir.mkdir(parents=True, exist_ok=False)
    results = {}
    for path in sorted(input_dir.glob("*.json")):
        if path.name == "report.json":
            continue
        document = json.loads(path.read_text())
        if not isinstance(document, dict) or "manifest" not in document or "rows" not in document:
            continue
        try:
            artifact = fit_prop_model(
                document,
                train_before=train_before,
                test_before=test_before,
                minimum_per_split=40,
            )
        except ValueError as exc:
            results[path.stem] = {"status": "UNAVAILABLE", "reason": str(exc)}
            continue
        sport = artifact["sport"]
        market = artifact["market"]
        destination = output_dir / sport
        destination.mkdir(exist_ok=True)
        (destination / f"{market}.json").write_text(
            json.dumps(artifact, indent=2, allow_nan=False) + "\n"
        )
        results[market] = {
            "status": artifact["stage"],
            "model_version": artifact["model_version"],
            "family": artifact["family"],
            "test_sample_count": artifact["validation"].get("test_sample_count", 0),
            "promotion_passed": artifact["validation"].get("promotion_passed", False),
        }
    (output_dir / "training-report.json").write_text(
        json.dumps(results, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--train-before", required=True)
    parser.add_argument("--test-before", required=True)
    args = parser.parse_args()
    train_directory(
        args.input_dir,
        args.output_dir,
        train_before=args.train_before,
        test_before=args.test_before,
    )
