from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tools import verify_goat_exact_line_inference as verify


def test_complete_feed_is_research_only_even_with_exact_inputs(monkeypatch):
    monkeypatch.setattr(verify, "collect_boost_odds", lambda *args, **kw:
        SimpleNamespace(coverage="FULL", odds_rows=3, rows=({"sport": "basketball_nba"},)))
    monkeypatch.setattr(verify, "audit_exact_line_research", lambda *args, **kw: {
        "status": "RESEARCH_ONLY", "exact_line_research_estimates": 2,
        "research_probability_sides": 4, "rejections": {},
        "crosswalk_truth_independently_confirmed_by_runtime": False,
        "prospective_calibration_verified": False,
        "joint_probability_verified": False,
        "betting_enabled": False, "production_approved": False,
    })
    result = verify.verify_private_goat_inference(
        object(), sport="NBA", game_ids=[77],
        crosswalks=[], snapshots=[], artifacts=[],
        observed_at=datetime.now(UTC),
    )
    assert result["status"] == "RESEARCH_ONLY"
    assert result["eligible_quote_rows"] == 3
    assert result["exact_line_research_estimates"] == 2
    assert result["production_approved"] is False
    assert result["joint_probability_verified"] is False


def test_incomplete_feed_never_calls_model_inference(monkeypatch):
    monkeypatch.setattr(verify, "collect_boost_odds", lambda *args, **kw:
        SimpleNamespace(coverage="PARTIAL", odds_rows=3, rows=()))
    monkeypatch.setattr(verify, "audit_exact_line_research",
                        lambda *args, **kw: (_ for _ in ()).throw(AssertionError("inference")))
    result = verify.verify_private_goat_inference(
        object(), sport="NFL", game_ids=[77],
        crosswalks=[], snapshots=[], artifacts=[],
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "INCOMPLETE_OR_EMPTY_PAID_PROP_FEED"
    assert result["betting_enabled"] is False


@pytest.mark.parametrize("sport,ids", [
    ("NHL", [77]), ("NBA", []), ("NFL", [77, 77]),
    ("NBA", [True]), ("NBA", [-1]), ("NBA", [1, 2, 3, 4]),
])
def test_invalid_scope_fails_before_paid_request(sport, ids):
    with pytest.raises(ValueError):
        verify.verify_private_goat_inference(
            object(), sport=sport, game_ids=ids,
            crosswalks=[], snapshots=[], artifacts=[],
        )


def test_private_json_rejects_missing_and_nonlist(tmp_path):
    with pytest.raises(ValueError):
        verify._private_json(tmp_path / "missing.json")
    path = tmp_path / "private.json"
    path.write_text('{"secret":"DO_NOT_LOG"}')
    with pytest.raises(ValueError):
        verify._private_json(path)


def test_missing_key_does_not_contact_provider(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("JABBAZI_BALLDONTLIE_API_KEY", raising=False)
    for name in ("crosswalks", "features", "artifacts"):
        (tmp_path / (name + ".json")).write_text("[]")
    monkeypatch.setattr(verify, "BallDontLieProvider",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network")))
    result = verify.main([
        "--sport", "NBA", "--game-id", "77",
        "--reviewed-crosswalks", str(tmp_path / "crosswalks.json"),
        "--frozen-features", str(tmp_path / "features.json"),
        "--fitted-artifacts", str(tmp_path / "artifacts.json"),
    ])
    assert result == 2
    assert "SPORTS_API_KEY_NOT_CONFIGURED" in capsys.readouterr().out
