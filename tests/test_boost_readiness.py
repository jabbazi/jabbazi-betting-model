from types import SimpleNamespace
from jabazi.boost_readiness import boost_model_readiness


def test_validating_marginal_cannot_approve_nhl_boost():
    model = SimpleNamespace(stage="VALIDATING", model_version="nhl-v1",
                            artifact={"validation": {"promotion_passed": False}})
    report = boost_model_readiness({("icehockey_nhl", "player_goals"): model})
    assert report["icehockey_nhl"]["automated_boost_recommendation_enabled"] is False
    assert report["icehockey_nhl"]["marginal_markets"]["player_goals"]["approved"] is False
    assert report["basketball_nba"]["joint_model_approved"] is False


def test_joint_model_needs_prospective_calibration():
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="nba-v1",
                            artifact={"validation": {"promotion_passed": True}})
    joint = SimpleNamespace(approved_for_betting=True,
                            prospective_calibration_passed=False)
    report = boost_model_readiness(
        {("basketball_nba", "player_points"): model},
        {"basketball_nba": joint})
    assert report["basketball_nba"]["automated_boost_recommendation_enabled"] is False

def test_joint_and_marginal_require_real_prospective_evidence():
    validation = {"promotion_passed": True, "prospective_sample_count": 0,
                  "brier": 0.15, "market_baseline_brier": 0.16, "ece": 0.04}
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="nba-v2",
                            artifact={"validation": validation})
    joint = SimpleNamespace(approved_for_betting=True, prospective_calibration_passed=True,
                            independent_benchmark_passed=True, prospective_sample_count=0,
                            calibration_ece=0.05)
    report = boost_model_readiness({("basketball_nba", "player_points"): model},
                                   {"basketball_nba": joint})["basketball_nba"]
    assert report["marginal_markets"]["player_points"]["approved"] is False
    assert report["joint_model_approved"] is False
    assert report["automated_boost_recommendation_enabled"] is False


def test_joint_requires_independent_benchmark_even_with_samples():
    validation = {"promotion_passed": True, "prospective_sample_count": 300,
                  "brier": 0.15, "market_baseline_brier": 0.16, "ece": 0.04}
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="nba-v2",
                            artifact={"validation": validation})
    joint = SimpleNamespace(approved_for_betting=True, prospective_calibration_passed=True,
                            independent_benchmark_passed=False, prospective_sample_count=300,
                            calibration_ece=0.05)
    report = boost_model_readiness({("basketball_nba", "player_points"): model},
                                   {"basketball_nba": joint})["basketball_nba"]
    assert report["marginal_markets"]["player_points"]["approved"] is True
    assert report["joint_model_approved"] is False
    assert report["automated_boost_recommendation_enabled"] is False


def test_joint_and_marginal_all_gates_needed_for_approval():
    validation = {"promotion_passed": True, "prospective_sample_count": 300,
                  "brier": 0.15, "market_baseline_brier": 0.16, "ece": 0.04}
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="nba-v2",
                            artifact={"validation": validation})
    joint = SimpleNamespace(approved_for_betting=True, prospective_calibration_passed=True,
                            independent_benchmark_passed=True, prospective_sample_count=300,
                            calibration_ece=0.05)
    report = boost_model_readiness({("basketball_nba", "player_points"): model},
                                   {"basketball_nba": joint})["basketball_nba"]
    assert report["joint_model_approved"] is True
    assert report["automated_boost_recommendation_enabled"] is True


def test_joint_rejects_nonfinite_or_boolean_evidence():
    validation = {"promotion_passed": True, "prospective_sample_count": True,
                  "brier": float("nan"), "market_baseline_brier": 0.2, "ece": 0.1}
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="nhl-v2",
                            artifact={"validation": validation})
    joint = SimpleNamespace(approved_for_betting=True, prospective_calibration_passed=True,
                            independent_benchmark_passed=True, prospective_sample_count=True,
                            calibration_ece=float("nan"))
    report = boost_model_readiness({("icehockey_nhl", "player_goals"): model},
                                   {"icehockey_nhl": joint})["icehockey_nhl"]
    assert report["joint_model_approved"] is False
    assert report["marginal_markets"]["player_goals"]["approved"] is False
