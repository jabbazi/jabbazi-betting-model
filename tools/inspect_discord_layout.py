"""One-shot Discord layout inspector. Prints only names/ids/positions; no secrets."""
from __future__ import annotations
import json, os
import httpx

API="https://discord.com/api/v10"

def main():
    token=os.getenv("JABBAZI_DISCORD_BOT_TOKEN","").strip()
    guild=os.getenv("JABBAZI_DISCORD_GUILD_ID","").strip()
    if not token or not guild:
        print("DISCORD_LAYOUT_INSPECT "+json.dumps({"status":"UNAVAILABLE"}), flush=True)
        return 1
    headers={"Authorization":"Bot "+token,"User-Agent":"JabbaziLayoutInspect/1.0"}
    with httpx.Client(base_url=API,headers=headers,timeout=20) as http:
        r=http.get(f"/guilds/{guild}/channels")
        r.raise_for_status()
        rows=r.json()
    cats=sorted([x for x in rows if x.get("type")==4], key=lambda x:x.get("position",0))
    texts=sorted([x for x in rows if x.get("type") in (0,5)], key=lambda x:(x.get("position",0),x.get("name","")))
    out={
      "status":"VERIFIED",
      "categories":[{"id":str(x["id"]),"name":x.get("name"),"position":x.get("position",0)} for x in cats],
      "matches":[{"id":str(x["id"]),"name":x.get("name"),"type":x.get("type"),"parent_id":str(x.get("parent_id") or ""),"position":x.get("position",0)} for x in rows if any(k in x.get("name","").lower() for k in ("nsf","nfs","logo"))],
      "all_nonstandard":[{"id":str(x["id"]),"name":x.get("name"),"type":x.get("type"),"parent_id":str(x.get("parent_id") or ""),"position":x.get("position",0)} for x in rows if x.get("type") not in (0,4,5)]
    }
    print("DISCORD_LAYOUT_INSPECT "+json.dumps(out,ensure_ascii=False), flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
