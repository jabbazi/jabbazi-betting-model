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
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="v2",
                            artifact={"validation": {"promotion_passed": True}},
                            estimate=lambda _: estimate)
    m = match_player_model(p, {(p.sport, p.market): model})
    assert m.status == "UNAVAILABLE"
    assert m.reason == "PLAYER_INTEGRITY_UNVERIFIED"


def approved_fixture():
    price = SimpleNamespace(sport="basketball_nba", market="player_points")
    estimate = SimpleNamespace(
        probability=Decimal(".65"), model_version="v2",
        feature_snapshot={"integrity": {field: True for field in (
            "event_identity", "player_identity", "role", "availability", "fresh_features")}})
    model = SimpleNamespace(stage="PRODUCTION_APPROVED", model_version="v2",
                            artifact={"validation": {"promotion_passed": True}},
                            estimate=lambda _: estimate)
    return price, model, estimate


def test_stage_label_alone_cannot_approve_probability():
    price, model, _ = approved_fixture()
    model.artifact = {"validation": {"promotion_passed": False}}
    model.estimate = lambda _: (_ for _ in ()).throw(AssertionError("must not estimate"))
    result = match_player_model(price, {(price.sport, price.market): model})
    assert result.probability is None
    assert result.reason == "MODEL_PROMOTION_EVIDENCE_MISSING"


def test_estimate_version_must_match_registry():
    price, model, estimate = approved_fixture()
    estimate.model_version = "different"
    result = match_player_model(price, {(price.sport, price.market): model})
    assert result.probability is None
    assert result.reason == "MODEL_VERSION_MISMATCH"


def test_approved_probability_retains_exact_model_version():
    price, model, _ = approved_fixture()
    result = match_player_model(price, {(price.sport, price.market): model})
    assert result.status == "MODEL_ESTIMATE"
    assert result.probability == Decimal(".65")
    assert result.model_version == "v2"


def test_malformed_feature_snapshot_fails_closed():
    price, model, estimate = approved_fixture()
    estimate.feature_snapshot = None
    result = match_player_model(price, {(price.sport, price.market): model})
    assert result.probability is None
    assert result.reason == "PLAYER_INTEGRITY_UNVERIFIED"
