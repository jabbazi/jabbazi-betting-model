"""Explicit GOAT sportsbook prop category to JABBAZI model market map.

Only source-documented market labels are mapped. A market match is not a
player identity match, feature snapshot, calibrated hit probability or wager.
"""
from __future__ import annotations

from collections.abc import Mapping

from jabazi.models.player_distribution import PLAYER_PROP_MARKETS
from jabazi.boost_scope import SPORTS

GOAT_TO_JABBAZI = {
    "NBA": {
        "points": "player_points", "rebounds": "player_rebounds",
        "assists": "player_assists", "threes": "player_threes",
        "blocks": "player_blocks", "steals": "player_steals",
        "double_double": "player_double_double",
        "points_rebounds": "player_points_rebounds",
        "points_assists": "player_points_assists",
        "rebounds_assists": "player_rebounds_assists",
        "points_rebounds_assists": "player_points_rebounds_assists",
    },
    "NFL": {
        "passing_yards": "player_pass_yds",
        "passing_attempts": "player_pass_attempts",
        "passing_completions": "player_pass_completions",
        "passing_tds": "player_pass_tds",
        "rushing_yards": "player_rush_yds",
        "rushing_attempts": "player_rush_attempts",
        "receiving_yards": "player_reception_yds",
        "receptions": "player_receptions",
        "anytime_td": "player_anytime_td",
    },
    "NHL": {
        "goals": "player_goals", "assists": "player_assists",
        "points": "player_points",
        "shots_on_goal": "player_shots_on_goal",
        "saves": "player_total_saves",
    },
}

for sport, markets in GOAT_TO_JABBAZI.items():
    if not set(markets.values()).issubset(PLAYER_PROP_MARKETS[SPORTS[sport]]):
        raise RuntimeError("GOAT-to-JABBAZI map references unsupported model market")


def summarize_goat_model_market_alignment(sport: str, observed_market_breadth: Mapping) -> dict:
    """Aggregate category alignment; never infer a model probability or entitlement.

    Does not claim that a specific model artifact exists, is trained or approved.
    """
    if sport not in GOAT_TO_JABBAZI:
        raise ValueError("Unsupported sport")
    if not isinstance(observed_market_breadth, Mapping):
        raise ValueError("Market breadth required")
    observed = observed_market_breadth.get("markets")
    if not isinstance(observed, Mapping):
        raise ValueError("Sanitized market breadth required")
    categories = []
    mapped_rows = 0
    unmapped_rows = 0
    for label, stats in sorted(observed.items()):
        if not isinstance(label, str) or not isinstance(stats, Mapping):
            raise ValueError("Invalid observed market")
        count = stats.get("accepted_quote_rows")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid accepted quote count")
        model_market = GOAT_TO_JABBAZI[sport].get(label)
        if model_market:
            mapped_rows += count
        else:
            unmapped_rows += count
        categories.append({
            "source_market": label,
            "jabbazi_market": model_market,
            "accepted_quote_rows": count,
            "mapping": "DOCUMENTED_CATEGORY_MATCH" if model_market else "UNMAPPED",
        })
    return {
        "sport": sport, "source": "BALLDONTLIE_SPORTS_API",
        "categories": categories, "mapped_quote_rows": mapped_rows,
        "unmapped_quote_rows": unmapped_rows,
        "category_mapping_verified": True,
        "specific_player_game_identity_verified": False,
        "fresh_pregame_feature_snapshot_verified": False,
        "model_artifact_and_version_verified": False,
        "model_hit_probability_verified": False,
        "joint_probability_verified": False,
        "betting_enabled": False, "approval": "RESEARCH_ONLY",
    }
