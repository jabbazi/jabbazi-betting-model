"""Build leakage-safe MLB player-prop distribution datasets from Retrosheet staging."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.capture_nfl_context import write_json

PITCHER_MARKETS = {
    "pitcher_strikeouts": ("p_k", "p_bfp", 8.0),
    "pitcher_outs": ("p_ipouts", "p_bfp", 8.0),
    "pitcher_hits_allowed": ("p_h", "p_bfp", 8.0),
    "pitcher_walks": ("p_w", "p_bfp", 8.0),
}
BATTER_MARKETS = {
    "batter_hits": ("b_h", "b_pa", 2.0),
    "batter_total_bases": ("total_bases", "b_pa", 2.0),
    "batter_home_runs": ("b_hr_binary", "b_pa", 2.0),
    "batter_rbis": ("b_rbi", "b_pa", 2.0),
    "batter_runs_scored": ("b_r", "b_pa", 2.0),
    "batter_hits_runs_rbis": ("hrr", "b_pa", 2.0),
    "batter_walks": ("b_w", "b_pa", 2.0),
}


def rolling(values, n):
    subset = list(values)[-n:]
    return sum(subset) / len(subset) if subset else 0.0


def stdev(values, n):
    subset = list(values)[-n:]
    if len(subset) < 2:
        return 0.0
    mean = sum(subset) / len(subset)
    return math.sqrt(sum((v-mean)**2 for v in subset) / len(subset))


def features(values, opportunities, role_value):
    return {
        "last1_value": values[-1] if values else 0.0,
        "mean3_value": rolling(values, 3),
        "mean5_value": rolling(values, 5),
        "mean10_value": rolling(values, 10),
        "mean20_value": rolling(values, 20),
        "std5_value": stdev(values, 5),
        "season_mean_value": rolling(values, max(1, len(values))),
        "last1_opportunities": opportunities[-1] if opportunities else 0.0,
        "mean3_opportunities": rolling(opportunities, 3),
        "mean5_opportunities": rolling(opportunities, 5),
        "mean10_opportunities": rolling(opportunities, 10),
        "games_prior": float(len(values)),
        "role_value": float(role_value),
    }


def load(path):
    rows = []
    with gzip.open(path, "rt") as source:
        for line in source:
            row = json.loads(line)
            rows.append(row)
    return rows


def numeric(row, name):
    value = row.get(name)
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid {name}")
    return result


def batter_derived(row):
    hits = numeric(row, "b_h")
    doubles = numeric(row, "b_d")
    triples = numeric(row, "b_t")
    homers = numeric(row, "b_hr")
    if None in (hits, doubles, triples, homers):
        return None
    singles = hits - doubles - triples - homers
    if singles < 0:
        raise ValueError("Impossible batter component totals")
    return {
        "total_bases": singles + 2*doubles + 3*triples + 4*homers,
        "b_hr_binary": float(homers > 0),
        "hrr": hits + numeric(row, "b_r") + numeric(row, "b_rbi"),
    }


def build_market(rows, market, value_field, opportunity_field, minimum_opps, *, pitcher):
    histories = defaultdict(lambda: deque(maxlen=64))
    opps = defaultdict(lambda: deque(maxlen=64))
    last_dates = {}
    result = []
    rows = sorted(rows, key=lambda r: (r["date"], r["gid"], r["id"]))
    for row in rows:
        if row.get("gametype") not in {"regular", "regular-season", "regular season"}:
            continue
        player = row["id"]
        values, opportunities = histories[player], opps[player]
        derived = {} if pitcher else (batter_derived(row) or {})
        observed = numeric(row, value_field) if value_field in row else derived.get(value_field)
        opportunity = numeric(row, opportunity_field)
        if observed is None or opportunity is None:
            continue
        if len(values) >= 5 and rolling(opportunities, 5) >= minimum_opps:
            game_date = datetime.strptime(row["date"], "%Y%m%d").replace(tzinfo=UTC)
            previous = last_dates.get(player)
            if previous is not None:
                available = previous + timedelta(days=1)
                start = game_date + timedelta(hours=23)  # conservative end-of-date boundary
                decision = start - timedelta(hours=2)
                if available < decision:
                    role = row.get("p_seq") if pitcher else row.get("b_lp")
                    role = 0 if role is None else float(role)
                    result.append({
                        "event_id": row["gid"],
                        "player_id": player,
                        "prediction_at": decision.isoformat(),
                        "starts_at": start.isoformat(),
                        "features_available_at": available.isoformat(),
                        "result_available_at": (start + timedelta(hours=12)).isoformat(),
                        "result_status": "final",
                        "observed_value": observed,
                        "expected_opportunities": rolling(opportunities, 5),
                        "features": features(values, opportunities, role),
                        "availability_basis": "prior_game_date_plus_one_day",
                    })
        values.append(observed)
        opportunities.append(opportunity)
        last_dates[player] = datetime.strptime(row["date"], "%Y%m%d").replace(tzinfo=UTC)
    return result


def main(pitching, batting, receipts, output):
    output.mkdir(parents=True, exist_ok=False)
    pitchers, batters = load(pitching), load(batting)
    receipt_data = json.loads(receipts.read_text())
    checksum = "".join(sorted(r.get("sha256", "") for r in receipt_data if r.get("sha256")))
    import hashlib
    source_checksum = hashlib.sha256(checksum.encode()).hexdigest()
    counts = {}
    for market, (value, opp, minimum) in PITCHER_MARKETS.items():
        rows = build_market(pitchers, market, value, opp, minimum, pitcher=True)
        doc = {
            "manifest": {
                "sport": "baseball_mlb",
                "market": market,
                "data_mode": "real",
                "provider": "Retrosheet",
                "source_checksum": source_checksum,
                "research_rights_reference": "https://www.retrosheet.org/downloads/csvdownloads.html",
                "evidence_mode": "historical_reconstruction_from_prior_completed_games",
                "market_lines_included": False,
            },
            "rows": rows,
        }
        write_json(output / f"{market}.json", doc)
        counts[market] = len(rows)
    for market, (value, opp, minimum) in BATTER_MARKETS.items():
        rows = build_market(batters, market, value, opp, minimum, pitcher=False)
        doc = {
            "manifest": {
                "sport": "baseball_mlb",
                "market": market,
                "data_mode": "real",
                "provider": "Retrosheet",
                "source_checksum": source_checksum,
                "research_rights_reference": "https://www.retrosheet.org/downloads/csvdownloads.html",
                "evidence_mode": "historical_reconstruction_from_prior_completed_games",
                "market_lines_included": False,
            },
            "rows": rows,
        }
        write_json(output / f"{market}.json", doc)
        counts[market] = len(rows)
    write_json(output / "report.json", {
        "generated_at": datetime.now(UTC).isoformat(),
        "markets": counts,
        "approved_for_betting": False,
        "note": "Distribution training only. Historical prop-line calibration is unavailable; production promotion requires frozen prospective evidence.",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pitching", required=True, type=Path)
    parser.add_argument("--batting", required=True, type=Path)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    main(args.pitching, args.batting, args.receipts, args.output)
