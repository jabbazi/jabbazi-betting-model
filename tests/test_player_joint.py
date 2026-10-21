from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from jabazi.models.player_joint import (
    JointPlayerModel,
    checkerboard_joint,
    load_joint_player_model,
    SPORT,
)
from jabazi.research.same_game import evaluate_same_game
from test_same_game import NOW, prices


def test_checkerboard_preserves_positive_and_negative_dependence_and_marginals():
    positive = [[i, i] for i in range(100)]
    negative = [[i, 99 - i] for i in range(100)]
    assert checkerboard_joint(positive, [0.5, 0.5], [True, True]) == pytest.approx(0.5)
    assert checkerboard_joint(negative, [0.5, 0.5], [True, True]) == pytest.approx(0)
    assert checkerboard_joint(positive, [0.5, 0.5], [True, False]) == pytest.approx(0)
    for p in (0.001, 0.123, 0.5, 0.997):
        assert checkerboard_joint(positive, [p, 1], [True, True]) == pytest.approx(p)
        assert checkerboard_joint(positive, [p, 1], [False, True]) == pytest.approx(p)


def setup_pair(bucket=None):
    joint = load_joint_player_model()
    assert joint is not None
    b = bucket or joint.artifact["buckets"][0]
    ps = [
        replace(
            prices()[0],
            market=m,
            participant="Player" + str(i if b["relationship"] == "same_team" else 0),
            selection="Over",
            line=D("3.5"),
        )
        for i, m in enumerate(b["markets"])
    ]
    es = []
    for i in range(2):
        snap = dict(
            player_id=str(i if b["relationship"] == "same_team" else 0),
            team="KC",
            features={"position_" + b["positions"][i].lower(): 1},
            integrity={
                k: True
                for k in (
                    "event_identity",
                    "player_identity",
                    "role",
                    "availability",
                    "fresh_features",
                    "injuries",
                )
            },
        )
        es.append(
            SimpleNamespace(
                probability=D(".5"),
                uncertainty=D(".1"),
                model_version=b["marginal_versions"][i],
                feature_snapshot=snap,
            )
        )
    models = {
        (SPORT, m): SimpleNamespace(estimate=lambda p, e=e: e) for m, e in zip(b["markets"], es)
    }
    return joint, ps, models, es


def test_fitted_player_joint_reaches_sgp_engine_and_stays_research_only():
    joint, ps, models, es = setup_pair()
    r = evaluate_same_game(ps, None, now=NOW, player_models=models, joint_player=joint)
    assert r["status"] == "PRICE_CHECK", r
    assert r["method"] == "empirical_residual_rank_checkerboard_copula"
    assert r["joint_probability"] > D(".25")
    assert r["marginal_probabilities"] == [D(".5"), D(".5")]
    assert r["recommended_stake_units"] is None and not r["approved_for_betting"]
    assert r["player_joint_evidence"]["holdout"]["season"] == 2025


def test_marginal_version_mismatch_and_bad_identity_fail_closed():
    joint, ps, models, es = setup_pair()
    es[0].model_version = "new-unfitted-model"
    r = evaluate_same_game(ps, None, now=NOW, player_models=models, joint_player=joint)
    assert r["reasons"] == ["JOINT_MARGINAL_VERSION_MISMATCH"]
    es[0].feature_snapshot["integrity"]["player_identity"] = False
    r = evaluate_same_game(ps, None, now=NOW, player_models=models, joint_player=joint)
    assert r["reasons"] == ["PLAYER_IDENTITY_OR_ROLE_UNVERIFIED"]


def test_cross_player_team_relationship_must_be_verified():
    j = load_joint_player_model()
    b = next(b for b in j.artifact["buckets"] if b["relationship"] == "same_team")
    joint, ps, models, es = setup_pair(b)
    result = evaluate_same_game(ps, None, now=NOW, player_models=models, joint_player=joint)
    assert result["reasons"] == ["PLAYER_CORRELATION_HOLDOUT_NOT_IMPROVED"]
    es[1].feature_snapshot["team"] = "BUF"
    result = evaluate_same_game(ps, None, now=NOW, player_models=models, joint_player=joint)
    assert result["reasons"] == ["VERIFIED_SAME_TEAM_REQUIRED"]


def test_invalid_rank_support_and_no_three_player_shortcut():
    joint, ps, models, _ = setup_pair()
    a = deepcopy(joint.artifact)
    a["buckets"][0]["ranks"][0] = [-1, 0]
    with pytest.raises(ValueError):
        JointPlayerModel(a)
    third = replace(ps[0], line=D("4.5"))
    r = evaluate_same_game(ps + [third], None, now=NOW, player_models=models, joint_player=joint)
    assert r["reasons"] == ["TWO_NFL_PLAYER_LEGS_REQUIRED"]
    r = evaluate_same_game(
        [ps[0], prices()[1]], object(), now=NOW, player_models=models, joint_player=joint
    )
    assert r["reasons"] == ["MIXED_TEAM_PLAYER_JOINT_MODEL_UNAVAILABLE"]


def test_holdout_and_training_are_separated_and_game_counts_not_pair_counts():
    artifact = load_joint_player_model().artifact
    assert artifact["fit_season"] == 2024 and artifact["holdout_season"] == 2025
    assert artifact["prospective_sample_count"] == 0
    for b in artifact["buckets"]:
        assert 100 <= b["training_unique_games"] <= 272
        assert b["training_unique_games"] <= len(b["ranks"])
        assert b["holdout"]["unique_games"] <= 272
        assert b["holdout"]["unique_games"] <= b["holdout"]["pairs"]
