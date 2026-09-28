"""Capture official public NHL results privately for a reproducible experiment.

python tools/capture_nhl_history.py --output /private/path --opening-date 2026-09-29
Do not commit the captured raw responses. This is not a sportsbook odds source.
"""

import argparse
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path


def capture(output, opening_date):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def get(club, season):
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{club}/{season}"
        req = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.3"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("Oversize NHL response")
        payload = json.loads(raw)
        if not payload.get("games"):
            raise ValueError("No NHL games")
        name = f"{club}-{season}.json"
        (output / name).write_bytes(raw)
        return payload, {
            "url": url,
            "file": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    receipts = []
    for season in (20222023, 20232024, 20242025, 20252026):
        payload, receipt = get("CAR", season)
        receipts.append(receipt)
        clubs = sorted(
            {g[side]["abbrev"] for g in payload["games"] for side in ("homeTeam", "awayTeam")}
            - {"CAR"}
        )
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts.extend(r[1] for r in pool.map(lambda club: get(club, season), clubs))
    (output / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    url = "https://api-web.nhle.com/v1/schedule/" + opening_date
    with urllib.request.urlopen(url, timeout=30) as r:
        raw = r.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("Oversize schedule")
    (output / "opening.json").write_bytes(raw)
    (output / "opening_receipt.json").write_text(
        json.dumps(
            {
                "url": url,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Captured {len(receipts)} club-seasons and opening schedule")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--opening-date", required=True)
    a = p.parse_args()
    capture(a.output, a.opening_date)
