"""Idempotently seed reviewed JABBAZI onboarding messages. Dry-run by default."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

API="https://discord.com/api/v10"
MARKER="JABBAZI_SETUP_V3"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    token=os.getenv("JABBAZI_DISCORD_BOT_TOKEN","")
    guild=os.getenv("JABBAZI_DISCORD_GUILD_ID","")
    owner=os.getenv("JABBAZI_DISCORD_OWNER_ID","")
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit("Discord token, guild ID and owner ID are required")
    content=json.loads(Path("docs/discord/seed_content.json").read_text())
    headers={"Authorization":"Bot "+token,"User-Agent":"JABBAZI-GURU/1.0"}
    with httpx.Client(base_url=API,headers=headers,timeout=20) as http:
        info=http.get(f"/guilds/{guild}").raise_for_status().json()
        if str(info["owner_id"])!=owner:
            raise SystemExit("Configured Discord owner mismatch")
        bot=http.get("/users/@me").raise_for_status().json()
        channels=http.get(f"/guilds/{guild}/channels").raise_for_status().json()
        blueprint=json.loads(Path("docs/discord/server_blueprint.json").read_text())
        parents={str(c["id"]):c["name"] for c in channels if c["type"]==4}
        expected={name:category["name"] for category in blueprint["categories"] for name in category["channels"]}
        by_name={c["name"]:c for c in channels if c["type"]==0
                 and parents.get(str(c.get("parent_id")))==expected.get(c["name"])}
        plan=[]
        for name,message in content.items():
            channel=by_name.get(name)
            if channel is None:
                plan.append({"channel":name,"status":"MISSING_CHANNEL"})
                continue
            recent=http.get(f"/channels/{channel['id']}/messages?limit=50").raise_for_status().json()
            previous = next((row for row in recent if str(row.get("author", {}).get("id")) == str(bot["id"])
                             and "JABBAZI_SETUP_V" in str(row.get("content") or "")), None)
            if previous and previous.get("content") == message:
                plan.append({"channel":name,"status":"ALREADY_SEEDED"})
                continue
            plan.append({"channel":name,"status":("UPDATE" if previous else "POST") if args.apply else "WOULD_UPDATE"})
            if args.apply:
                payload={"content":message,"allowed_mentions":{"parse":[]}}
                if previous:
                    response=http.patch(f"/channels/{channel['id']}/messages/{previous['id']}",json=payload)
                else:
                    response=http.post(f"/channels/{channel['id']}/messages",json=payload)
                response.raise_for_status()
        print(json.dumps({"mode":"APPLIED" if args.apply else "DRY_RUN","plan":plan},indent=2))


if __name__=="__main__":
    main()
