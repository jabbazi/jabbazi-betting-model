from copy import deepcopy

from jabazi.models.player_distribution import (
    MLB_PROP_MARKETS,
    NFL_PROP_MARKETS,
    raw_probability,
)
from jabazi.models.train_player_props import promotion_decision
from jabazi.reliability.layer import prospective_stage


def count_artifact():
    return {
        "artifact_type": "player_prop_distribution",
        "sport": "baseball_mlb",
        "market": "pitcher_strikeouts",
        "family": "count_nb",
        "feature_names": ["usage"],
        "scaler": {"mean": [0.0], "scale": [1.0]},
        "parameters": {"coef": [0.0], "intercept": 1.7, "dispersion": 0.25},
        "model_version": "test-k",
        "stage": "SHADOW_ONLY",
    }


def binary_artifact():
    return {
        "artifact_type": "player_prop_distribution",
        "sport": "americanfootball_nfl",
        "market": "player_anytime_td",
        "family": "binary_logistic",
        "feature_names": ["red_zone_share"],
        "scaler": {"mean": [0.0], "scale": [1.0]},
        "parameters": {"coef": [0.75], "intercept": -0.5},
        "model_version": "test-atd",
        "stage": "SHADOW_ONLY",
    }


def yards_artifact():
    return {
        "artifact_type": "player_prop_distribution",
        "sport": "americanfootball_nfl",
        "market": "player_reception_yds",
        "family": "hurdle_lognormal",
        "feature_names": ["routes"],
        "scaler": {"mean": [0.0], "scale": [1.0]},
        "parameters": {
            "active_coef": [0.0],
            "active_intercept": 4.0,
            "mean_coef": [0.0],
            "mean_intercept": 4.0,
            "sigma": 0.45,
        },
        "model_version": "test-yards",
        "stage": "SHADOW_ONLY",
    }


def test_requested_nfl_markets_are_modeled():
    required = {
        "player_pass_yds",
        "player_pass_attempts",
        "player_pass_completions",
        "player_pass_tds",
        "player_rush_yds",
        "player_rush_attempts",
        "player_receptions",
        "player_reception_yds",
        "player_anytime_td",
    }
    assert required <= NFL_PROP_MARKETS


def test_requested_mlb_markets_are_modeled():
    required = {
        "pitcher_strikeouts",
        "pitcher_outs",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_rbis",
        "batter_runs_scored",
    }
    assert required <= MLB_PROP_MARKETS


def test_count_ladder_is_monotone():
    artifact = count_artifact()
    features = {"usage": 0.0}
    over_35 = raw_probability(artifact, features, "over", 3.5)
    over_45 = raw_probability(artifact, features, "over", 4.5)
    over_55 = raw_probability(artifact, features, "over", 5.5)
    assert 1 > over_35 >= over_45 >= over_55 > 0


def test_binary_anytime_touchdown_complements():
    artifact = binary_artifact()
    features = {"red_zone_share": 0.3}
    yes = raw_probability(artifact, features, "yes", 0.5)
    no = raw_probability(artifact, features, "no", 0.5)
    assert abs((yes + no) - 1.0) < 1e-12


def test_yards_probability_comes_from_distribution_not_mean():
    artifact = yards_artifact()
    features = {"routes": 0.0}
    over_25 = raw_probability(artifact, features, "over", 25.5)
    over_55 = raw_probability(artifact, features, "over", 55.5)
    assert 1 > over_25 > over_55 > 0
    # A projected mean would be measured in yards, while the result must be a probability.
    assert over_25 < 1.0


def test_player_model_cannot_backtest_itself_into_production():
    artifact = count_artifact()
    artifact["validation"] = {
        "test_sample_count": 2000,
        "brier": 0.19,
        "market_baseline_brier": 0.22,
        "ece": 0.02,
        "calibration_slope": 1.0,
    }
    promoted = promotion_decision(artifact, None)
    assert promoted["stage"] != "PRODUCTION_APPROVED"
    assert promoted["validation"]["promotion_passed"] is False


def test_player_model_production_requires_strict_prospective_evidence():
    artifact = count_artifact()
    artifact["validation"] = {
        "test_sample_count": 2000,
        "brier": 0.19,
        "market_baseline_brier": 0.22,
        "ece": 0.02,
        "calibration_slope": 1.0,
    }
    prospective = {
        "sample_count": 800,
        "brier": 0.20,
        "market_baseline_brier": 0.225,
        "ece": 0.025,
        "clv_sample_count": 250,
        "mean_clv_prob_points": 0.4,
        "data_health_failures": 0,
    }
    promoted = promotion_decision(artifact, prospective)
    assert promoted["stage"] == "PRODUCTION_APPROVED"
    assert promoted["validation"]["promotion_passed"] is True


def test_team_bucket_cannot_promote_on_sample_size_alone():
    record = {
        "model": {"n": 1500, "brier": 0.24, "log_loss": 0.69},
        "market": {"n": 1500, "brier": 0.22, "log_loss": 0.66},
        "calibration": [{"n": 1500, "mean_probability": 0.60, "observed_hit_rate": 0.60}],
        "identity_failures": 0,
        "input_verified": 1500,
    }
    stage, approved, _ = prospective_stage(record)
    assert stage != "PRODUCTION_APPROVED"
    assert approved is False


def test_team_bucket_can_promote_only_when_market_beaten_and_calibrated():
    record = {
        "model": {"n": 1500, "brier": 0.205, "log_loss": 0.60},
        "market": {"n": 1500, "brier": 0.215, "log_loss": 0.62},
        "calibration": [
            {"n": 750, "mean_probability": 0.55, "observed_hit_rate": 0.545},
            {"n": 750, "mean_probability": 0.65, "observed_hit_rate": 0.655},
        ],
        "identity_failures": 0,
        "input_verified": 1500,
    }
    stage, approved, _ = prospective_stage(record)
    assert stage == "PRODUCTION_APPROVED"
    assert approved is True
