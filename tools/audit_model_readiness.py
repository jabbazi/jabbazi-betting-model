"""Read committed artifacts and reports. No network, credentials, or model mutation."""

import json
from pathlib import Path

from jabazi.research.model_audit import audit_report


def main():
    root = Path(__file__).resolve().parents[1]
    reports = {}
    for sport in ("nfl", "mlb"):
        report = json.loads(
            (root / f"docs/experiments/score-distributions/{sport}-report.json").read_text()
        )
        artifact = json.loads(
            (root / f"src/jabazi/models/artifacts/{sport}_scores.json").read_text()
        )
        reports[sport] = audit_report(report, artifact)
    print(json.dumps(reports, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
