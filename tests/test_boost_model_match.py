from types import SimpleNamespace
from decimal import Decimal
from jabazi.boost_model_match import match_player_model


def test_missing_model_never_invents_probability():
    p = SimpleNamespace(sport="icehockey_nhl", market="player_goals")
    m = match_player_model(p, {})
    assert m.probability is None
    assert m.status == "UNAVAILABLE"


def test_shadow_model_not_approved():
    p = SimpleNamespace(sport="basketball_nba", market="player_points")
    model = SimpleNamespace(stage="SHADOW_ONLY", model_version="v1")
    m = match_player_model(p, {(p.sport, p.market): model})
    assert m.status == "RESEARCH_ONLY"
    assert m.probability is None


def test_approved_model_requires_identity():
    p = SimpleNamespace(sport="americanfootball_nfl", market="player_receptions")
    estimate = SimpleNamespace(probability=Decimal(".65"), model_version="v2",
                               feature_snapshot={"integrity": {"player_identity": True}})
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", estimate=lambda _: estimate)
    m = match_player_model(p, {(p.sport, p.market): model})
    assert m.status == "UNAVAILABLE"
    assert m.reason == "PLAYER_INTEGRITY_UNVERIFIED"
