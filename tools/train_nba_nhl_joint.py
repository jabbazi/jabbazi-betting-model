"""Fit isolated historical NBA/NHL joint experiments; never edit live artifacts."""
import argparse
import json
from pathlib import Path

from jabazi.research.joint_player_fit import SPECS, fit_joint_research
from jabazi.research.nba_player_experiment import build_datasets
from jabazi.research.nhl_player_experiment import build_dataset
from tools.train_nhl_player_props import load_schedule, load_stats, checksum


def run(args):
    sport = args.sport
    markets = sorted({m for pair, _ in SPECS[sport] for m in pair})
    if sport == "basketball_nba":
        if not args.nba_history:
            raise ValueError("Captured normalized NBA history required")
        payload = json.loads(Path(args.nba_history).read_text())
        documents = build_datasets(
            rows=payload["rows"], markets=markets, provider=payload["provider"],
            source_checksum=payload["source_checksum"],
            research_rights_reference=payload["research_rights_reference"])
    else:
        if not args.schedule_dir or not args.stats_dir:
            raise ValueError("Captured official NHL schedule and player history required")
        games, schedules = load_schedule(args.schedule_dir)
        skaters, files = load_stats(args.stats_dir, "skater")
        for file in files:
            captured = json.loads(file.read_text())
            total = captured.get("total")
            if type(total) is not int or total != len(captured["data"]):
                raise ValueError("NHL history coverage missing or truncated")
        source = checksum(schedules + files)
        documents = {m: build_dataset(
            games=games, skater_rows=skaters, goalie_rows=[], market=m,
            source_checksum=source, research_rights_reference=args.rights_reference)
                     for m in markets}
    root = Path(args.marginals) / sport
    marginals = {m: json.loads((root / (m + ".json")).read_text()) for m in markets}
    artifact = fit_joint_research(
        documents, marginals, sport=sport, fit_start=args.fit_start,
        test_start=args.test_start, test_end=args.test_end)
    output = Path(args.output).resolve()
    repo = Path(__file__).resolve().parents[1]
    for protected in (repo / "models", repo / "src"):
        if output == protected or protected in output.parents:
            raise ValueError("Research output must not overwrite deployed model paths")
    output.mkdir(parents=True, exist_ok=True)
    receipt_paths = ([Path(args.nba_history).parent / "receipts.json"]
                     if sport == "basketball_nba" else
                     [args.schedule_dir / "receipts.json", args.stats_dir / "receipts.json"])
    receipts = [json.loads(p.read_text()) for p in receipt_paths]
    (output / "source_receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    (output / "artifact.json").write_text(json.dumps(artifact, separators=(",", ":")))
    report = {**artifact, "buckets": [{k: v for k, v in b.items() if k != "ranks"}
                                     for b in artifact["buckets"]]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", choices=sorted(SPECS), required=True)
    parser.add_argument("--nba-history")
    parser.add_argument("--schedule-dir", type=Path)
    parser.add_argument("--stats-dir", type=Path)
    parser.add_argument("--rights-reference", default="Public source research; commercial rights unverified")
    parser.add_argument("--marginals", default="models/player_props")
    parser.add_argument("--output", required=True)
    parser.add_argument("--fit-start", default="2024-07-01T00:00:00+00:00")
    parser.add_argument("--test-start", default="2025-07-01T00:00:00+00:00")
    parser.add_argument("--test-end", default="2026-07-01T00:00:00+00:00")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
