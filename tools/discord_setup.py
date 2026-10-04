"""Build a new JABBAZI server's roles/channels. Default is an offline plan.

The owner creates the empty server in Discord and installs their own bot first.
This utility does not create accounts, collect payments, or send messages.
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request

VIEW = 1 << 10
SEND = 1 << 11
HISTORY = 1 << 16
EMBED = 1 << 14
THREADS = (1 << 35) | (1 << 36) | (1 << 38)
VIP = "JABBAZI VIP"
ANALYST = "JABBAZI Analyst"
LAYOUT = [
    (
        "START HERE",
        "public",
        [
            ("welcome", False),
            ("rules", False),
            ("how-to-read-picks", False),
            ("announcements", False),
        ],
    ),
    (
        "COMMUNITY",
        "public",
        [("free-picks", False), ("public-results", False), ("sports-chat", True), ("help", True)],
    ),
    (
        "VIP PICKS",
        "vip",
        [
            ("daily-card", False),
            ("mlb-picks", False),
            ("nfl-picks", False),
            ("college-football-picks", False),
            ("parlays-and-alternates", False),
            ("price-updates", False),
            ("vip-chat", True),
        ],
    ),
    (
        "OWNER DESK",
        "owner",
        [("scanner-review", False), ("model-health", False), ("operations", False)],
    ),
]


def overwrites(guild, vip, analyst, bot, access, chat=False):
    public = access == "public"
    everyone = {
        "id": guild,
        "type": 0,
        "allow": str(VIEW | HISTORY if public else 0),
        "deny": str((0 if public else VIEW) | (0 if public and chat else SEND | THREADS)),
    }
    values = [
        everyone,
        {"id": analyst, "type": 0, "allow": str(VIEW | SEND | HISTORY | EMBED), "deny": "0"},
        {"id": bot, "type": 1, "allow": str(VIEW | SEND | HISTORY | EMBED), "deny": "0"},
    ]
    if access == "vip":
        values.append(
            {
                "id": vip,
                "type": 0,
                "allow": str(VIEW | HISTORY | (SEND if chat else 0)),
                "deny": str(0 if chat else SEND | THREADS),
            }
        )
    return values


class Discord:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, payload=None):
        for attempt in range(4):
            req = urllib.request.Request(
                "https://discord.com/api/v10" + path,
                data=None if payload is None else json.dumps(payload).encode(),
                method=method,
                headers={
                    "Authorization": "Bot " + self.token,
                    "Content-Type": "application/json",
                    "User-Agent": "JabbaziSetup/0.2",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    delay = float(json.load(e).get("retry_after", 1))
                    if delay > 30:
                        raise RuntimeError("Rate limited; rerun later") from None
                    time.sleep(max(0.1, delay))
                    continue
                raise RuntimeError(f"Discord returned HTTP {e.code} for {method} {path}") from None
        raise RuntimeError("Discord rate limit persisted; rerun later")


def setup(client, guild, owner):
    info = client.request("GET", f"/guilds/{guild}")
    if str(info["owner_id"]) != owner:
        raise ValueError("Configured owner does not own the selected server")
    bot = str(client.request("GET", "/users/@me")["id"])
    roles = client.request("GET", f"/guilds/{guild}/roles")
    ids = {}
    for name, color in [(VIP, 0x8B5CF6), (ANALYST, 0xF5B942)]:
        matches = [r for r in roles if r["name"] == name]
        if len(matches) > 1:
            raise ValueError("Duplicate named roles; resolve before running")
        role = (
            matches[0]
            if matches
            else client.request(
                "POST",
                f"/guilds/{guild}/roles",
                {"name": name, "color": color, "permissions": "0", "mentionable": False},
            )
        )
        if int(role.get("permissions", "0")) != 0:
            raise ValueError("Existing JABBAZI role has unexpected global privileges")
        ids[name] = str(role["id"])
    channels = client.request("GET", f"/guilds/{guild}/channels")
    created = {}
    for category, access, children in LAYOUT:
        perms = overwrites(guild, ids[VIP], ids[ANALYST], bot, access)
        matches = [c for c in channels if c["type"] == 4 and c["name"] == category]
        if len(matches) > 1:
            raise ValueError("Duplicate category names")
        payload = {"name": category, "type": 4, "permission_overwrites": perms}
        if matches:
            parent = client.request(
                "PATCH", f"/channels/{matches[0]['id']}", {"permission_overwrites": perms}
            )
        else:
            parent = client.request("POST", f"/guilds/{guild}/channels", payload)
        for name, chat in children:
            permissions = overwrites(guild, ids[VIP], ids[ANALYST], bot, access, chat)
            matches = [
                c for c in channels if c["name"] == name and c.get("parent_id") == parent["id"]
            ]
            if len(matches) > 1:
                raise ValueError("Duplicate channel names")
            payload = {
                "name": name,
                "type": 0,
                "parent_id": parent["id"],
                "permission_overwrites": permissions,
            }
            if matches:
                channel = client.request(
                    "PATCH", f"/channels/{matches[0]['id']}", {"permission_overwrites": permissions}
                )
            else:
                channel = client.request("POST", f"/guilds/{guild}/channels", payload)
            created[name] = channel["id"]
    return {"guild_id": guild, "roles": ids, "channels": created}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="Create/update the named roles and channels"
    )
    args = parser.parse_args()
    if not args.apply:
        print(
            json.dumps(
                {
                    "server": "JABBAZI GURU",
                    "mode": "OFFLINE PLAN",
                    "roles": [VIP, ANALYST],
                    "layout": LAYOUT,
                },
                indent=2,
            )
        )
        return
    from jabazi.config import load_dotenv

    load_dotenv()
    token = os.environ.get("JABBAZI_DISCORD_BOT_TOKEN", "")
    guild = os.environ.get("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.environ.get("JABBAZI_DISCORD_OWNER_ID", "")
    if not token or not guild.isdigit() or not owner.isdigit():
        parser.error("Bot token, server ID, and owner ID must be configured securely")
    print(json.dumps(setup(Discord(token), guild, owner), indent=2))


if __name__ == "__main__":
    main()
