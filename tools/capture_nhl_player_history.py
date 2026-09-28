"""Capture official NHL per-game skater and goalie summaries for offline prop research.

Example:
    python tools/capture_nhl_player_history.py --output /private/nhl-player-history

Raw captures are intentionally written outside the repository. They are historical
outcomes, not sportsbook prices and not evidence of a betting edge.
"""
import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SEASONS = (20222023, 20232024, 20242025, 20252026)
BASE = "https://api.nhle.com/stats/rest/en"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.4"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read(64_000_001)
    if len(raw) > 64_000_000:
        raise ValueError("NHL stats response exceeds capture limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected NHL Stats REST response")
    return raw, payload


def capture(output, seasons=SEASONS):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipts = []
    for season in seasons:
        for kind in ("skater", "goalie"):
            query = urllib.parse.urlencode({
                "isAggregate": "false",
                "isGame": "true",
                "start": "0",
                "limit": "-1",
                "cayenneExp": f"seasonId={int(season)} and gameTypeId=2",
            })
            url = f"{BASE}/{kind}/summary?{query}"
            raw, payload = get(url)
            required = {"playerId", "gameId", "gameDate"}
            if payload["data"] and not required <= set(payload["data"][0]):
                raise ValueError(f"NHL {kind} per-game schema missing identity fields")
            name = f"{kind}-{int(season)}.json"
            (output / name).write_bytes(raw)
            receipts.append({
                "url": url,
                "file": name,
                "rows": len(payload["data"]),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(),
            })
    manifest = {
        "provider": "NHL Stats REST",
        "captured_at": datetime.now(UTC).isoformat(),
        "seasons": [int(s) for s in seasons],
        "receipts": receipts,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["capture_checksum"] = hashlib.sha256(canonical).hexdigest()
    (output / "receipts.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({
        "seasons": len(seasons),
        "files": len(receipts),
        "rows": sum(r["rows"] for r in receipts),
        "capture_checksum": manifest["capture_checksum"],
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seasons", nargs="*", type=int, default=list(SEASONS))
    args = parser.parse_args()
    capture(args.output, tuple(args.seasons))
