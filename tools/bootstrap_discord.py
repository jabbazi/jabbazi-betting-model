"""Repair and compact the live JABBAZI Discord safely.

Dry-run by default. --apply creates/moves only managed JABBAZI objects and repairs
permissions on BOTH existing and new channels. --archive-obsolete moves superseded
JABBAZI channels into a hidden staff archive instead of deleting history.
"""
from __future__ import annotations

import argparse
import json
import os

import httpx

VIEW = 1 << 10
SEND = 1 << 11
READ_HISTORY = 1 << 16
API = "https://discord.com/api/v10"

def resolve_role(roles, *, env_name, fallback_name):
    configured = os.getenv(env_name, "").strip()
    if configured:
        matches = [r for r in roles if str(r["id"]) == configured]
        if len(matches) != 1:
            raise SystemExit(f"{env_name} does not match a role in this guild")
        return matches[0]
    matches = [r for r in roles if r["name"] == fallback_name]
    if not matches:
        raise SystemExit(
            f"No {fallback_name!r} role exists; set {env_name} to the intended role ID"
        )
    # Duplicate legacy names are tolerated; configured ID remains authoritative.
    return matches[0]


def checked(response, operation):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise RuntimeError(f"DISCORD_OPERATION_{operation}_HTTP_{status}") from None
    return response


def put_overwrite(http, channel_id, target_id, target_type, allow, deny):
    checked(
        http.put(
            f"/channels/{channel_id}/permissions/{target_id}",
            json={"type": target_type, "allow": str(allow), "deny": str(deny)},
        ),
        "PUT_PERMISSION_OVERWRITE",
    )


def main():
    from jabazi.discord_migration import migrate
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-obsolete", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(apply=args.apply, archive_obsolete=args.archive_obsolete), indent=2))


if __name__ == "__main__":
    main()
