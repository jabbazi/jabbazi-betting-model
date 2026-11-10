"""Synthetic training fixtures; these are not real model validation evidence."""
from copy import deepcopy
import pytest

from jabazi.research.joint_player_fit import (
    SPECS, fit_joint_research, joint_evaluator, scores,
)
from jabazi.models.player_joint import checkerboard_joint


def inputs(sport):
    docs, models = {}, {}
    for market in {m for pair, _ in SPECS[sport] for m in pair}:
        rows = []
        for year in (2024, 2025):
            for day in (1, 2):
                date = f"{year}-10-{day:02}"
                rows.append({
                    "event_id": date, "player_id": "fixture-player",
                    "prediction_at": date + "T12:00:00Z",
                    "starts_at": date + "T19:00:00Z",
                    "features_available_at": date + "T10:00:00Z",
                    "result_available_at": date + "T23:00:00Z",
                    "result_status": "final", "observed_value": day,
                    "features": {"x": 1.0}, "expected_opportunities": 20,
                })
        docs[market] = {"manifest": {"sport": sport, "market": market,
            "data_mode": "real", "provider": "SYNTHETIC UNIT FIXTURE",
            "source_checksum": "test-only", "research_rights_reference": "test-only"},
            "rows": rows}
        models[market] = {"sport": sport, "market": market, "family": "count_nb",
            "training_cutoff": "2024-01-01T00:00:00Z", "model_version": market+"-fixture",
            "calibration": None, "feature_names": ["x"],
            "scaler": {"mean": [0.0], "scale": [1.0]},
            "parameters": {"coef": [0.0], "intercept": 1.0, "dispersion": .2}}
    return docs, models


def fit(docs, models, sport="basketball_nba", **kwargs):
    return fit_joint_research(docs, models, sport=sport,
        fit_start="2024-07-01T00:00:00Z", test_start="2025-07-01T00:00:00Z",
        test_end="2026-07-01T00:00:00Z", minimum_events=kwargs.get("minimum_events", 2))


@pytest.mark.parametrize("sport", list(SPECS))
def test_fits_dependence_without_claiming_prospective_or_market_evidence(sport):
    docs, models = inputs(sport)
    artifact = fit(docs, models, sport)
    assert len(artifact["buckets"]) == 3
    assert all(b["status"] == "HISTORICAL_RESEARCH_FIT" for b in artifact["buckets"])
    assert artifact["prospective_sample_count"] == 0
    assert artifact["approved_for_betting"] is False
    assert artifact["market_baseline_verified"] is False
    assert artifact == fit(docs, models, sport)


def test_holdout_values_cannot_change_fitted_ranks():
    docs, models = inputs("basketball_nba")
    before = fit(docs, models)
    for doc in docs.values():
        for row in doc["rows"][2:]:
            row["observed_value"] = 40
    after = fit(docs, models)
    assert [b["ranks"] for b in before["buckets"]] == [b["ranks"] for b in after["buckets"]]
    assert before["model_version"] == after["model_version"]


@pytest.mark.parametrize("mutation", ["future_training", "calibrated", "future_features", "duplicate", "wrong_sport", "event_mismatch"])
def test_invalid_history_rejected(mutation):
    docs, models = inputs("basketball_nba")
    market = "player_points"
    if mutation == "future_training":
        models[market]["training_cutoff"] = "2025-01-01T00:00:00Z"
    elif mutation == "calibrated":
        models[market]["calibration"] = {"method": "isotonic"}
    elif mutation == "future_features":
        docs[market]["rows"][0]["features_available_at"] = "2026-01-01T00:00:00Z"
    elif mutation == "duplicate":
        docs[market]["rows"].append(deepcopy(docs[market]["rows"][0]))
    elif mutation == "wrong_sport":
        docs[market]["manifest"]["sport"] = "icehockey_nhl"
    else:
        docs[market]["rows"][0]["starts_at"] = "2024-10-01T20:00:00Z"
    with pytest.raises(ValueError):
        fit(docs, models)


def test_many_players_in_two_games_cannot_satisfy_game_minimum():
    docs, models = inputs("basketball_nba")
    for doc in docs.values():
        originals = deepcopy(doc["rows"])
        doc["rows"] += [dict(r, player_id=str(i)) for r in originals for i in range(10)]
    assert all(b["status"] == "INSUFFICIENT_INDEPENDENT_EVENTS"
               for b in fit(docs, models, minimum_events=3)["buckets"])


def test_scores_weight_games_equally():
    rows = [("first", .9, .5, 1), ("second", .1, .5, 1)]
    base = scores(rows)
    repeated = scores(rows + [rows[0]] * 20)
    assert base["joint"]["event_weighted_brier"] == pytest.approx(
        repeated["joint"]["event_weighted_brier"])
    assert base["paired_game_bootstrap_95pct"]["brier_improvement"] == pytest.approx(
        repeated["paired_game_bootstrap_95pct"]["brier_improvement"])
    assert base["event_weighted_ece"] == pytest.approx(repeated["event_weighted_ece"])


def test_vectorized_copula_matches_reference():
    pytest.importorskip("numpy")
    ranks = [[i, 999-i] for i in range(1000)]
    evaluate = joint_evaluator(ranks)
    for ps in ([.3333, .7777], [0, 1], [1, 1], [.1, .2]):
        assert evaluate(ps) == pytest.approx(checkerboard_joint(ranks, ps, [True, True]))
