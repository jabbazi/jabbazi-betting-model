"""Privately register ALREADY independently reviewed provider-to-model identities.

Dry-run is the default. This tool does not create attestations, infer identity
from names, promote models, access provider APIs, or display player records.
"""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from jabazi.paid_player_evidence import register_reviewed_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", choices=("NBA", "NFL", "NHL"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--commit-reviewed-manifest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.input.is_file() or args.input.is_symlink() or not 0 < args.input.stat().st_size <= 5_000_000:
            raise ValueError("Invalid private input")
        records = json.loads(args.input.read_text(encoding="utf-8"))
        report = register_reviewed_manifest(None, args.sport, records, now=datetime.now(UTC))
        if args.commit_reviewed_manifest and report["registration_allowed"]:
            from jabazi.api import platform_store
            store = platform_store()
            try:
                report = register_reviewed_manifest(store, args.sport, records,
                                                   now=datetime.now(UTC), commit=True)
            finally:
                store.close()
        print(json.dumps(report, sort_keys=True))
        return 0 if report["registration_allowed"] else 1
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        print(json.dumps({"status": "UNAVAILABLE", "reason": "REVIEWED_MANIFEST_INVALID_OR_UNAVAILABLE",
                          "committed": False, "betting_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
