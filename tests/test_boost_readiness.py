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
