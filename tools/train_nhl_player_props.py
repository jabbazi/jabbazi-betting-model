"""Build and fit research-only NHL player-prop artifacts from private captures.

Expected inputs:
- schedule-dir: raw files created by tools/capture_nhl_history.py
- stats-dir: raw files created by tools/capture_nhl_player_history.py

Example:
    python tools/train_nhl_player_props.py \
      --schedule-dir /private/nhl-history \
      --stats-dir /private/nhl-player-history \
      --output /private/nhl-player-artifacts \
      --research-rights-reference "owner-reviewed NHL public API research use"

The command never writes to models/player_props automatically. Promotion and deployment
remain separate reviewed actions.
"""
import argparse
import hashlib
import json
from pathlib import Path

from jabazi.models.train_player_props import fit_prop_model
from jabazi.models.train_opportunity import fit_opportunity_model
from jabazi.providers.nhl import rows as schedule_rows
from jabazi.research.nhl_player_experiment import INITIAL_MARKETS, build_dataset
from jabazi.research.prop_data import inspect_prop_dataset

TRAIN_BEFORE = "2024-07-01T00:00:00+00:00"
TEST_BEFORE = "2025-07-01T00:00:00+00:00"


def load_json(path):
    return json.loads(Path(path).read_text())


def load_schedule(directory):
    payloads = []
    files = []
    for path in sorted(Path(directory).glob("*.json")):
        payload = load_json(path)
        if isinstance(payload, dict) and isinstance(payload.get("games"), list):
            payloads.append(payload)
            files.append(path)
    if not payloads:
        raise ValueError("No captured NHL club schedules found")
    return schedule_rows(payloads), files


def load_stats(directory, kind):
    result, files = [], []
    for path in sorted(Path(directory).glob(f"{kind}-*.json")):
        payload = load_json(path)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ValueError(f"Invalid captured NHL {kind} stats")
        result.extend(data)
        files.append(path)
    if not files:
        raise ValueError(f"No captured NHL {kind} stats found")
    return result, files


def checksum(paths):
    digest = hashlib.sha256()
    for path in sorted(set(map(Path, paths)), key=lambda p: str(p)):
        digest.update(str(path.name).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run(schedule_dir, stats_dir, output, rights_reference):
    if not rights_reference.strip():
        raise ValueError("A reviewed research-rights reference is required")
    games, schedule_files = load_schedule(schedule_dir)
    skaters, skater_files = load_stats(stats_dir, "skater")
    goalies, goalie_files = load_stats(stats_dir, "goalie")
    source_checksum = checksum(schedule_files + skater_files + goalie_files)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    report = {
        "source_checksum": source_checksum,
        "train_before": TRAIN_BEFORE,
        "test_before": TEST_BEFORE,
        "markets": {},
        "opportunity_models": {},
        "approved_for_betting": False,
    }
    documents = {}
    for market in sorted(INITIAL_MARKETS):
        document = build_dataset(
            games=games,
            skater_rows=skaters,
            goalie_rows=goalies,
            market=market,
            source_checksum=source_checksum,
            research_rights_reference=rights_reference,
        )
        documents[market] = document
        inspection = inspect_prop_dataset(
            document,
            train_before=TRAIN_BEFORE,
            test_before=TEST_BEFORE,
            minimum_per_split=100,
        )
        market_report = {"inspection": inspection, "artifact": None}
        (output / f"{market}-dataset.json").write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        )
        if inspection["status"] == "READY_FOR_RESEARCH_FIT":
            artifact = fit_prop_model(
                document,
                train_before=TRAIN_BEFORE,
                test_before=TEST_BEFORE,
                minimum_per_split=100,
            )
            if artifact["stage"] == "PRODUCTION_APPROVED":
                raise ValueError("Historical NHL training must never self-promote")
            (output / f"{market}.json").write_text(json.dumps(artifact, indent=2) + "\n")
            market_report["artifact"] = {
                "model_version": artifact["model_version"],
                "stage": artifact["stage"],
                "family": artifact["family"],
                "distribution_validation": artifact["distribution_validation"],
                "validation": artifact["validation"],
            }
        report["markets"][market] = market_report

    for label, market in (
        ("time_on_ice", "player_points"),
        ("shots_faced", "player_total_saves"),
    ):
        artifact = fit_opportunity_model(
            documents[market],
            train_before=TRAIN_BEFORE,
            test_before=TEST_BEFORE,
            minimum_per_split=100,
        )
        (output / f"opportunity_{label}.json").write_text(
            json.dumps(artifact, indent=2) + "\n"
        )
        report["opportunity_models"][label] = {
            "model_version": artifact["model_version"],
            "stage": artifact["stage"],
            "validation": artifact["validation"],
        }

    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-dir", required=True)
    parser.add_argument("--stats-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--research-rights-reference", required=True)
    args = parser.parse_args()
    run(
        args.schedule_dir,
        args.stats_dir,
        args.output,
        args.research_rights_reference,
    )
