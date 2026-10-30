"""Research-only NBA/NHL joint ticket calibration report from local frozen JSONL.

No source data is transmitted or exported. Output contains ONLY metrics,
file checksum, no player/ticket/event identifiers and no betting approval.
Input files must originate from a genuine timestamped, owner-verifiable archive.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from jabazi.boost_joint_evidence import audit_frozen_joint_evidence


def inspect_local_archive(path, *, max_rows=1_000_000):
    """Validate local JSONL and emit aggregate evidence without raw records."""
    file = Path(path)
    digest = sha256()
    rows = []
    try:
        with file.open("rb") as stream:
            for line in stream:
                digest.update(line)
                if not line.strip():
                    continue
                if len(line) > 256_000:
                    raise ValueError("Evidence row exceeds safe size")
                if len(rows) >= max_rows:
                    raise ValueError("Evidence row safety cap exceeded")
                try:
                    entry = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    raise ValueError("Invalid evidence JSONL") from None
                rows.append(entry)
    except OSError:
        raise ValueError("Evidence file unavailable") from None
    report = audit_frozen_joint_evidence(rows)
    return {
        "input_sha256": digest.hexdigest(),
        "research_only": True,
        **report,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Evaluate genuine frozen NBA/NHL joint-ticket research history",
    )
    parser.add_argument("--input", required=True, help="Private local JSONL path")
    args = parser.parse_args(argv)
    try:
        result = inspect_local_archive(args.input)
    except ValueError:
        print(json.dumps({
            "status": "INVALID_OR_UNVERIFIED_EVIDENCE",
            "research_only": True,
            "approved_for_betting": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    # This exit code represents eligibility for manual review, NOT promotion.
    return 0 if result["all_requested_sports_verified"] and all(
        x["status"] == "REQUIRES_PROSPECTIVE_EXPERT_REVIEW"
        for x in result["reports"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
