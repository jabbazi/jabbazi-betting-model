"""NBA prospective-result extraction from authenticated final BALLDONTLIE stats.

Maps NBA boxscore fields to the EXACT same target definitions used to fit the
existing JABBAZI NBA player distributions. Requires final-game provenance and
a separately reviewed cross-provider identity manifest. Never treats missing
stats or DNP as zero. This prepares immutable research labels; it does not
approve models or write to a database by itself.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import re

from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.research.nba_player_experiment import COMPONENTS, _target

NBA_MARKETS = tuple(sorted((*COMPONENTS, "player_double_double")))
_FIELDS = {
    "points": "pts", "rebounds": "reb", "assists": "ast",
    "threes": "fg3m", "blocks": "blk", "steals": "stl",
    "turnovers": "turnover",
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.utcoffset() is not None else None


def _minutes(value):
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    try:
        if ":" in text:
            whole, part = text.split(":", 1)
            if not whole.isdigit() or not part.isdigit() or int(part) >= 60:
                return None
            result = int(whole) + int(part) / 60
        else:
            result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def _numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 and number.is_integer() else None


def prepare_nba_final_labels(game, stats, reviewed_crosswalks, *, observed_at):
    """Return private result rows and de-identified counts, never raw source rows."""
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError("Aware result observation required")
    if (not isinstance(game, dict) or not isinstance(stats, list)
            or not isinstance(reviewed_crosswalks, list)
            or len(stats) > 200 or len(reviewed_crosswalks) > 200):
        raise ValueError("Bounded final-game evidence required")
    now = observed_at.astimezone(UTC)
    game_id = game.get("id")
    start = _time(game.get("datetime"))
    if (type(game_id) is not int or game_id <= 0
            or game.get("status_state") != "final"
            or start is None or not start < now):
        raise ValueError("Authenticated completed NBA game required")
    reasons = Counter()
    index = {}
    ambiguous = set()
    for row in reviewed_crosswalks:
        if not isinstance(row, dict):
            reasons["invalid_crosswalk_schema"] += 1
            continue
        player = row.get("bdl_player_id")
        reviewed = _time(row.get("reviewed_at"))
        claimed_start = _time(row.get("event_starts_at"))
        checksum = row.get("source_record_sha256")
        declared = row.get("record_sha256")
        if (row.get("sport") != "NBA" or row.get("bdl_game_id") != game_id
                or type(player) is not int or player <= 0
                or row.get("source_namespace") != "ESPN"
                or not isinstance(row.get("source_player_id"), str)
                or not row["source_player_id"].strip()
                or not isinstance(row.get("canonical_event_id"), str)
                or not row["canonical_event_id"]
                or not isinstance(row.get("canonical_participant"), str)
                or not row["canonical_participant"]
                or row.get("independent_source_reviewed") is not True
                or reviewed is None or not reviewed <= now
                or claimed_start != start
                or not isinstance(checksum, str) or not _DIGEST.fullmatch(checksum)
                or not isinstance(declared, str) or declared != crosswalk_digest(row)):
            reasons["crosswalk_identity_or_provenance_unverified"] += 1
            continue
        if player in index:
            ambiguous.add(player)
        else:
            index[player] = row
    for player in ambiguous:
        del index[player]
    reasons["ambiguous_crosswalks"] += len(ambiguous)
    result_rows = []
    seen = set()
    for row in stats:
        if not isinstance(row, dict):
            reasons["invalid_stat_schema"] += 1
            continue
        nested_game, nested_player = row.get("game"), row.get("player")
        gid = nested_game.get("id") if isinstance(nested_game, dict) else None
        pid = nested_player.get("id") if isinstance(nested_player, dict) else None
        if gid != game_id or type(pid) is not int or pid <= 0:
            reasons["foreign_game_or_player_stat"] += 1
            continue
        if pid in seen:
            reasons["duplicate_player_stat"] += 1
            continue
        seen.add(pid)
        mapping = index.get(pid)
        if mapping is None:
            reasons["no_independently_reviewed_player_mapping"] += 1
            continue
        if _minutes(row.get("min")) is None:
            reasons["dnp_or_minutes_unverified"] += 1
            continue
        components = {name: _numeric(row.get(field)) for name, field in _FIELDS.items()}
        if any(value is None for value in components.values()):
            reasons["incomplete_final_boxscore"] += 1
            continue
        if 3 * components["threes"] > components["points"]:
            reasons["incoherent_final_boxscore"] += 1
            continue
        checksum = sha256(json.dumps(
            {"game": game, "stat": row}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=True,
        ).encode()).hexdigest()
        for market in NBA_MARKETS:
            result_rows.append({
                "sport": "basketball_nba",
                "event_id": mapping["canonical_event_id"],
                "participant": mapping["canonical_participant"],
                "market": market,
                "observed_value": _target(components, market),
                "starts_at": start.isoformat(),
                "observed_at": now.isoformat(),
                "source_checksum": checksum,
                "result_status": "final",
            })
    return {
        "sport": "NBA", "observed_at": now.isoformat(),
        "final_players_prepared": len(result_rows) // len(NBA_MARKETS),
        "final_market_labels_prepared": len(result_rows),
        "rejections": dict(sorted(reasons.items())),
        "_private_result_rows": result_rows,
        "source_truth_independently_verified_by_runtime": False,
        "prospective_calibration_validated": False,
        "betting_enabled": False, "production_approved": False,
    }
