"""Opportunity-first player projection contract.

The first-stage model predicts exposure (minutes, routes, targets, carries, attempts,
TOI, plate appearances, batters faced). Outcome distributions may then condition on
that exposure. This module is research-only until sport-specific opportunity artifacts
pass the same prospective gates as outcome models.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


OPPORTUNITY_UNITS={
    "americanfootball_nfl":{
        "player_pass_yds":"pass_attempts",
        "player_pass_completions":"pass_attempts",
        "player_pass_tds":"pass_attempts",
        "player_rush_yds":"rush_attempts",
        "player_receptions":"targets",
        "player_reception_yds":"targets",
        "player_anytime_td":"high_value_opportunities",
    },
    "basketball_nba":{
        "player_points":"minutes",
        "player_rebounds":"minutes",
        "player_assists":"minutes",
        "player_threes":"minutes",
        "player_blocks":"minutes",
        "player_steals":"minutes",
        "player_turnovers":"minutes",
        "player_points_rebounds_assists":"minutes",
        "player_points_rebounds":"minutes",
        "player_points_assists":"minutes",
        "player_rebounds_assists":"minutes",
        "player_double_double":"minutes",
    },
    "icehockey_nhl":{
        "player_points":"time_on_ice",
        "player_assists":"time_on_ice",
        "player_goals":"time_on_ice",
        "player_shots_on_goal":"time_on_ice",
        "player_total_saves":"shots_faced",
    },
    "baseball_mlb":{
        "pitcher_strikeouts":"batters_faced",
        "pitcher_outs":"batters_faced",
        "pitcher_hits_allowed":"batters_faced",
        "pitcher_walks":"batters_faced",
        "batter_hits":"plate_appearances",
        "batter_total_bases":"plate_appearances",
        "batter_home_runs":"plate_appearances",
        "batter_rbis":"plate_appearances",
        "batter_runs_scored":"plate_appearances",
        "batter_hits_runs_rbis":"plate_appearances",
        "batter_walks":"plate_appearances",
    },
}


@dataclass(frozen=True)
class OpportunityEstimate:
    mean: float
    low: float
    high: float
    unit: str
    model_version: str
    inputs_verified: bool
    approved_for_betting: bool=False

    def __post_init__(self):
        values=(self.mean,self.low,self.high)
        if any(not math.isfinite(v) or v<0 for v in values) or not self.low<=self.mean<=self.high:
            raise ValueError("Invalid opportunity estimate")
        if not self.unit or not self.model_version:
            raise ValueError("Opportunity provenance required")


def required_unit(sport,market):
    return OPPORTUNITY_UNITS.get(sport,{}).get(market)


def opportunity_adjustment(*, baseline_opportunity, estimate:OpportunityEstimate,
                           elasticity=1.0, lower=0.5, upper=1.5):
    """Return a bounded multiplicative exposure adjustment for an outcome mean."""
    baseline=float(baseline_opportunity)
    if not math.isfinite(baseline) or baseline<=0 or not 0<=elasticity<=2:
        raise ValueError("Invalid opportunity baseline")
    ratio=estimate.mean/baseline
    adjusted=ratio**elasticity
    return min(upper,max(lower,adjusted))
