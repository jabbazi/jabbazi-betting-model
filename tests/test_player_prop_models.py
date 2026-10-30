from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jabazi.models.player_distribution import (
    MLB_PROP_MARKETS,
    NBA_PROP_MARKETS,
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


def test_requested_nba_markets_are_registered_but_need_real_artifacts():
    required = {
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_points_rebounds_assists",
        "player_points_rebounds",
        "player_points_assists",
        "player_rebounds_assists",
        "player_double_double",
    }
    assert required <= NBA_PROP_MARKETS


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
    artifact["distribution_validation"] = {"n": 2000, "mae": 1.0, "rmse": 1.5, "mean_bias": 0.0}
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
    artifact["distribution_validation"] = {"n": 2000}
    artifact["validation"] = {
        "test_sample_count": 2000,
        "brier": 0.19,
        "market_baseline_brier": 0.22,
        "ece": 0.02,
        "calibration_slope": 1.0,
    }
    prospective = {
        "sample_count": 800,
        "independent_event_count": 800,
        "identity_failures": 0,
        "brier": 0.20,
        "market_baseline_brier": 0.225,
        "ece": 0.025,
        "clv_sample_count": 250,
        "clv_independent_event_count": 250,
        "mean_clv_prob_points": 0.4,
        "data_health_failures": 0,
    }
    promoted = promotion_decision(artifact, prospective)
    assert promoted["stage"] == "PRODUCTION_APPROVED"
    assert promoted["validation"]["promotion_passed"] is True
    prospective["independent_event_count"] = 1
    assert promotion_decision(artifact, prospective)["stage"] == "VALIDATING"
    prospective["independent_event_count"] = 800
    prospective["identity_failures"] = 1
    assert promotion_decision(artifact, prospective)["stage"] == "VALIDATING"


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


def test_player_snapshot_is_market_specific():
    from types import SimpleNamespace
    from jabazi.models.player_distribution import PlayerPropModel

    artifact = count_artifact()
    artifact["stage"] = "SHADOW_ONLY"

    class Store:
        def list_records(self, kind, limit, entity=None):
            assert kind == "player_feature_snapshot"
            # Wrong-market data must never be accepted even if feature names match.
            return [{
                "payload": {
                    "sport": "baseball_mlb",
                    "event_id": "game-1",
                    "participant": "Pitcher A",
                    "market": "pitcher_outs",
                    "features": {"usage": 0.0},
                    "integrity": {},
                }
            }]

    model = PlayerPropModel(artifact, Store())
    price = SimpleNamespace(
        sport="baseball_mlb",
        event_id="game-1",
        market="pitcher_strikeouts",
        participant="Pitcher A",
        in_play=False,
        selection="over",
        line=4.5,
    )
    assert model.estimate(price) is None


def test_research_only_snapshot_can_drive_probability_but_never_betting_approval():
    from jabazi.models.player_distribution import PlayerPropModel
    from jabazi.research.player_features import archive_player_feature_snapshot

    captured = {}

    class ArchiveStore:
        def append(self, kind, entity, payload, key=None):
            captured.update(kind=kind, entity=entity, payload=payload, key=key)
            return True

    now = datetime.now(UTC)
    archive_player_feature_snapshot(
        ArchiveStore(),
        sport="americanfootball_nfl",
        event_id="game-1",
        participant="Player A",
        market="player_anytime_td",
        player_id="00-1",
        starts_at=(now + timedelta(hours=4)).isoformat(),
        features_available_at=now.isoformat(),
        features={"red_zone_share": 0.3},
        expected_opportunities=8.0,
        integrity={
            "event_identity": True,
            "player_identity": True,
            "fresh_features": True,
            "schema": True,
            "role": True,
            "availability": True,
            "injuries": False,
            "no_duplicate_event": True,
        },
        provider="nflverse-history+depth-chart",
        source_checksum="abc123",
        feature_schema_version="test-v1",
        research_only=True,
    )
    assert captured["payload"]["research_only"] is True
    assert captured["payload"]["production_inputs_verified"] is False
    assert captured["payload"]["integrity"]["injuries"] is False

    artifact = binary_artifact()
    artifact["stage"] = "PRODUCTION_APPROVED"
    artifact["validation"] = {"promotion_passed": True, "prospective_sample_count": 1000}

    class ModelStore:
        def list_records(self, kind, limit, entity=None):
            assert kind == "player_feature_snapshot"
            return [{"payload": captured["payload"]}]

    model = PlayerPropModel(artifact, ModelStore())
    price = SimpleNamespace(
        sport="americanfootball_nfl",
        event_id="game-1",
        market="player_anytime_td",
        participant="Player A",
        in_play=False,
        selection="yes",
        line=None,
        starts_at=now + timedelta(hours=4),
    )
    estimate = model.estimate(price)
    assert estimate is not None
    assert 0 < float(estimate.probability) < 1
    assert estimate.approved_for_betting is False
    assert estimate.feature_snapshot["production_inputs_verified"] is False


def test_live_nfl_history_uses_previous_and_current_season(monkeypatch):
    import gzip
    from jabazi.providers.player_features_live import LivePlayerFeatureCollector

    header = [
        "player_id", "player_display_name", "position", "season", "week", "season_type",
        "game_id", "team", "completions", "attempts", "passing_yards", "passing_tds",
        "carries", "rushing_yards", "rushing_tds", "receptions", "targets",
        "receiving_yards", "receiving_tds",
    ]

    def asset(season, week):
        values = {
            "player_id": "00-TEST",
            "player_display_name": "Player Test",
            "position": "RB",
            "season": str(season),
            "week": str(week),
            "season_type": "REG",
            "game_id": f"{season}_{week}",
            "team": "DET",
            "completions": "0",
            "attempts": "0",
            "passing_yards": "0",
            "passing_tds": "0",
            "carries": "10",
            "rushing_yards": "50",
            "rushing_tds": "1",
            "receptions": "2",
            "targets": "3",
            "receiving_yards": "15",
            "receiving_tds": "0",
        }
        text = ",".join(header) + "\n" + ",".join(values[name] for name in header) + "\n"
        return gzip.compress(text.encode())

    def fetch(url, timeout=30):
        return asset(2025, 18) if "2025" in url else asset(2026, 1)

    monkeypatch.setattr("jabazi.providers.player_features_live._fetch_bytes", fetch)
    collector = LivePlayerFeatureCollector(now=datetime(2026, 9, 26, tzinfo=UTC))
    rows = collector._nfl_history()
    assert {int(row["season"]) for row in rows} == {2025, 2026}
    assert len({row["_source_checksum"] for row in rows}) == 1


def test_espn_injury_report_can_verify_clear_current_status(monkeypatch):
    from jabazi.providers.player_features_live import LivePlayerFeatureCollector

    now = datetime(2026, 9, 28, 18, tzinfo=UTC)
    collector = LivePlayerFeatureCollector(now=now, production_verified=False)
    monkeypatch.setattr(
        collector,
        "_nfl_card_context",
        lambda card: {
            "week": 3,
            "home_abbr": "CHI",
            "away_abbr": "PHI",
            "home": "Chicago Bears",
            "away": "Philadelphia Eagles",
            "start": card.starts_at,
        },
    )
    monkeypatch.setattr(
        "jabazi.providers.player_features_live._fetch_json",
        lambda url, timeout=20, headers=None: {
            "injuries": [{
                "team": {"abbreviation": "PHI"},
                "injuries": [],
            }]
        },
    )
    card = SimpleNamespace(
        event="Philadelphia Eagles @ Chicago Bears",
        starts_at=now + timedelta(hours=6),
    )
    evidence = collector._nfl_injury_evidence(
        card,
        "Test Player",
        {"team": "PHI", "gsis_id": "00-TEST"},
    )
    assert evidence["verified"] is True
    assert evidence["available_by_injury_report"] is True
    assert evidence["status"] == "not_listed"


def test_binary_historical_row_without_explicit_side_defaults_to_positive():
    from jabazi.models.train_player_props import _threshold_rows

    artifact = binary_artifact()
    rows = [{
        "features": {"red_zone_share": 0.3},
        "observed_value": 1,
        "market_side": None,
        "market_line": None,
    }]
    threshold = _threshold_rows(rows, artifact)
    assert len(threshold) == 1
    _, probability, outcome = threshold[0]
    assert 0 < probability < 1
    assert outcome == 1
