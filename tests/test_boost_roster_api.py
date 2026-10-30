"""Authenticated private roster candidate diagnostic, never a wagering API."""
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi import boost_api
from jabazi.chatgpt_api import scanner_key
from tools import prepare_goat_roster_candidates as probe


def _config(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    monkeypatch.setenv("JABBAZI_BALLDONTLIE_API_KEY", "PRIVATE_GOAT_KEY")


def test_authenticated_nba_candidate_probe_returns_counts_only(monkeypatch):
    _config(monkeypatch)
    called = []
    class FakeProvider:
        def __init__(self, key, *, budget):
            assert key == "PRIVATE_GOAT_KEY"
            assert budget == 15
        def close(self):
            called.append("closed")
    def fake_audit(provider, *, sport, calendar_date, max_games, max_prop_pages):
        assert sport == "NBA"
        assert str(calendar_date) == "2026-10-30"
        assert max_games == 1
        assert max_prop_pages == 5
        called.append("audited")
        return {
            "status": "CANDIDATES_ONLY",
            "reason": "INDEPENDENT_IDENTITY_REVIEW_REQUIRED",
            "games_considered": 1,
            "eligible_quote_rows": 7,
            "provider_player_rows": 3,
            "candidate_count": 2,
            "rejections": {"ambiguous_identity_factors": 1},
            "_private_candidates": [
                {"source_player_id": "PRIVATE_ESPN_123",
                 "bdl_player_id": 888, "player_name": "SECRET ATHLETE"}
            ],
            "api_key": "PRIVATE_GOAT_KEY",
            "betting_enabled": True,  # Must never be propagated.
        }
    monkeypatch.setattr(boost_api, "BallDontLieProvider", FakeProvider)
    monkeypatch.setattr(probe, "audit_date_candidates", fake_audit)
    client = TestClient(app)
    response = client.post(
        "/v1/chatgpt/boost-roster-candidate-diagnostic",
        json={"sport": "NBA", "slate_date": "2026-10-30"},
        headers={"Authorization": "Bearer " + scanner_key()},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["identity_candidate_count"] == 2
    assert data["eligible_quote_rows"] == 7
    assert data["independently_verified_crosswalks"] == 0
    assert data["calibrated_exact_line_probabilities_verified"] is False
    assert data["betting_enabled"] is False
    assert data["production_approved"] is False
    assert response.headers["cache-control"] == "no-store"
    assert called == ["audited", "closed"]
    for secret in ("PRIVATE_ESPN_123", "SECRET ATHLETE", "PRIVATE_GOAT_KEY", "888"):
        assert secret not in response.text


def test_missing_auth_rejected_before_paid_provider(monkeypatch):
    _config(monkeypatch)
    monkeypatch.setattr(boost_api, "BallDontLieProvider",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid call")))
    response = TestClient(app).post(
        "/v1/chatgpt/boost-roster-candidate-diagnostic",
        json={"sport": "NFL", "slate_date": "2026-11-01"},
    )
    assert response.status_code == 401


def test_nhl_not_eligible_for_nba_nfl_crosswalk_endpoint(monkeypatch):
    _config(monkeypatch)
    response = TestClient(app).post(
        "/v1/chatgpt/boost-roster-candidate-diagnostic",
        json={"sport": "NHL", "slate_date": "2026-10-30"},
        headers={"Authorization": "Bearer " + scanner_key()},
    )
    assert response.status_code == 422


def test_research_only_when_no_candidate_rows(monkeypatch):
    _config(monkeypatch)
    class FakeProvider:
        def __init__(self, *a, **k):
            pass
        def close(self):
            pass
    monkeypatch.setattr(boost_api, "BallDontLieProvider", FakeProvider)
    monkeypatch.setattr(probe, "audit_date_candidates", lambda *a, **k: {
        "status": "UNAVAILABLE", "reason": "GAME_DISCOVERY_UNAVAILABLE",
        "candidate_count": 0,
    })
    response = TestClient(app).post(
        "/v1/chatgpt/boost-roster-candidate-diagnostic",
        json={"sport": "NFL", "slate_date": "2026-11-01"},
        headers={"Authorization": "Bearer " + scanner_key()},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UNAVAILABLE"
    assert data["identity_candidate_count"] == 0
    assert data["production_approved"] is False
