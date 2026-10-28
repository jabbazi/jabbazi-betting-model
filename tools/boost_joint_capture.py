"""Manual, private CLI for immutable NBA/NHL joint research evidence.

Requires an existing initialized JABBAZI platform DB and explicit write flag.
No provider credentials, raw ticket payloads, player IDs or source documents
are printed. No scan, prediction, betting, deployment or Discord action.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jabazi.boost_prospective import (
    audit_ready_rows, archive_joint_outcome, freeze_joint_ticket,
)
from jabazi.boost_joint_evidence import audit_frozen_joint_evidence
from jabazi.boost_prospective_inventory import capture_inventory


def _open_store():
    from jabazi.api import platform_store
    return platform_store()


def _read_private_json(path):
    file = Path(path)
    try:
        if file.stat().st_size > 512_000:
            raise ValueError("Input exceeds 512KB cap")
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise ValueError("Unreadable or invalid private input") from None
    if not isinstance(data, dict):
        raise ValueError("One private JSON object required")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="JABBAZI private, append-only joint evidence capture",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("freeze", "settle"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--commit-evidence", action="store_true")
    sub.add_parser("audit")
    sub.add_parser("inventory")
    args = parser.parse_args(argv)
    if args.action in {"freeze", "settle"} and not args.commit_evidence:
        print(json.dumps({
            "status": "EXPLICIT_EVIDENCE_WRITE_FLAG_REQUIRED",
            "approved_for_betting": False,
        }))
        return 2
    try:
        payload = _read_private_json(args.input) if args.action in {"freeze", "settle"} else None
        store = _open_store()
        try:
            if args.action == "freeze":
                report = freeze_joint_ticket(store, payload)
                safe = {
                    "status": "FROZEN" if report["created"] else "ALREADY_FROZEN",
                    "forecast_id": report["forecast_id"],
                    "approved_for_betting": False,
                }
            elif args.action == "settle":
                if not all(key in payload for key in (
                    "forecast_id", "leg_results", "result_source",
                )):
                    raise ValueError("Missing settlement evidence")
                report = archive_joint_outcome(
                    store, forecast_id=payload["forecast_id"],
                    leg_results=payload["leg_results"],
                    result_source=payload["result_source"],
                )
                safe = {
                    "status": report["status"],
                    "created": report["created"],
                    "approved_for_betting": False,
                }
            elif args.action == "inventory":
                safe = capture_inventory(store)
            else:
                inventory = capture_inventory(store)
                if inventory["integrity_failures"]:
                    safe = {
                        "status": "INTEGRITY_BLOCKED",
                        "inventory": inventory,
                        "approved_for_betting": False,
                    }
                else:
                    rows = audit_ready_rows(store)
                    report = audit_frozen_joint_evidence(rows)
                    safe = {
                        "status": "RESEARCH_ONLY",
                        "inventory": inventory,
                        "eligible_resolved_tickets": len(rows),
                        "report": report,
                        "approved_for_betting": False,
                    }
        finally:
            store.close()
    except Exception:
        # Never dump private event, provider error body or DB credentials.
        print(json.dumps({
            "status": "INVALID_OR_UNAVAILABLE_EVIDENCE",
            "approved_for_betting": False,
        }))
        return 2
    print(json.dumps(safe, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
