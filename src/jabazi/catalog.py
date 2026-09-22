"""Expandable multisport catalog merged from the uploaded V2 starter.

Provider keys are capabilities, not promises. Actual coverage is discovered per
event and sportsbook and missing markets are never synthesized.
"""

SPORTS: dict[str, tuple[str, ...]] = {
    "MLB": ("baseball_mlb",),
    "NFL": ("americanfootball_nfl",),
    "NCAAF": ("americanfootball_ncaaf",),
    "NBA": ("basketball_nba",),
    "WNBA": ("basketball_wnba",),
    "NCAAB": ("basketball_ncaab",),
    "NHL": ("icehockey_nhl",),
    "TENNIS": ("tennis_atp_*", "tennis_wta_*"),
    "SOCCER": ("soccer_*",),
    "GOLF": ("golf_*",),
    "MMA": ("mma_mixed_martial_arts",),
    "BOXING": ("boxing_boxing",),
    "MOTORSPORT": ("motorsport_*",),
    "ESPORTS": ("esports_*",),
}

FEATURED_MARKETS = ("h2h", "spreads", "totals", "outrights")

MARKET_FAMILIES: dict[str, tuple[str, ...]] = {
    "alternate_lines": ("alternate_spreads", "alternate_totals", "alternate_team_totals"),
    "periods": ("h2h_h1", "spreads_h1", "totals_h1", "h2h_q1", "spreads_q1", "totals_q1"),
    "baseball_pitcher": (
        "pitcher_strikeouts",
        "pitcher_outs",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "pitcher_earned_runs",
        "pitcher_record_a_win",
    ),
    "baseball_batter": (
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_rbis",
        "batter_runs_scored",
        "batter_walks",
        "batter_strikeouts",
        "batter_stolen_bases",
    ),
    "basketball_player": (
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_blocks",
        "player_steals",
        "player_turnovers",
        "player_points_rebounds_assists",
        "player_double_double",
    ),
    "football_player": (
        "player_pass_yds",
        "player_pass_tds",
        "player_pass_attempts",
        "player_pass_completions",
        "player_pass_interceptions",
        "player_rush_yds",
        "player_rush_attempts",
        "player_receptions",
        "player_reception_yds",
    ),
    "hockey_player": (
        "player_points",
        "player_assists",
        "player_goals",
        "player_shots_on_goal",
        "player_total_saves",
        "player_blocked_shots",
    ),
    "soccer": (
        "btts",
        "double_chance",
        "correct_score",
        "to_qualify",
        "player_shots",
        "player_shots_on_target",
        "player_goals",
        "player_assists",
    ),
}


def expand_alternates(markets: tuple[str, ...]) -> tuple[str, ...]:
    """Include provider-standard `_alternate` ladders without duplicating keys."""
    result = list(markets)
    for market in markets:
        if market.startswith(("player_", "pitcher_", "batter_")) and not market.endswith(
            "_alternate"
        ):
            result.append(f"{market}_alternate")
    return tuple(dict.fromkeys(result))


def known_market(market: str) -> bool:
    if market in FEATURED_MARKETS or market.endswith("_alternate"):
        return True
    return any(market in markets for markets in MARKET_FAMILIES.values())
