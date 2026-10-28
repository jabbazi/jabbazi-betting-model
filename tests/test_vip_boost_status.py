"""VIP boost readiness is authenticated, quota-free and never actionable."""
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.vip import api as vip_api
from jabazi.vip import model_cache


def test_boost_status_requires_vip_session():
    response = TestClient(app).get("/v1/vip/boost/status")
    assert response.status_code == 401


def test_boost_status_fails_closed_without_cached_model_evidence(monkeypatch):
    monkeypatch.setattr(model_cache, "status", lambda loader: {
        "state": "REFRESHING", "data": None,
    })
    payload = vip_api.boost_status(ctx=(object(), {"tier": "VIP"})).body.decode()
    import json
    value = json.loads(payload)
    assert value["state"] == "REFRESHING"
    assert value["decision"] == "PASS"
    assert value["paid_requests_made"] == 0
    assert not value["betting_enabled"]
    assert len(value["sports"]) == 3
    assert all(s["player_model_stage"] == "UNAVAILABLE"
               for s in value["sports"])


def test_boost_status_surfaces_only_sanitized_stage_counts(monkeypatch):
    def fake_status(loader):
        return {"state": "READY", "data": {
            "models": [
                {"sport": "basketball_nba", "player_status": "VALIDATING",
                 "player_market_buckets": {
                     "player_points": {
                         "stage": "VALIDATING", "approved_for_betting": False,
                         "prospective_sample_count": 0,
                         "private_player_payload": "SECRET_DO_NOT_EXPOSE",
                     },
                 }},
                {"sport": "icehockey_nhl", "player_status": "VALIDATING",
                 "player_market_buckets": {}},
                {"sport": "baseball_mlb", "player_status": "PRODUCTION_APPROVED",
                 "player_market_buckets": {
                     "other": {"secret": "SECRET_DO_NOT_EXPOSE"},
                 }},
            ],
        }}
    monkeypatch.setattr(model_cache, "status", fake_status)
    response = vip_api.boost_status(ctx=(object(), {"tier": "VIP"}))
    import json
    payload = json.loads(response.body)
    assert payload["state"] == "READY"
    assert payload["decision"] == "PASS"
    assert payload["paid_requests_made"] == 0
    assert [s["sport"] for s in payload["sports"]] == ["NBA", "NFL", "NHL"]
    nba = payload["sports"][0]
    assert nba["player_model_stage"] == "VALIDATING"
    assert nba["player_markets"] == [{
        "market": "player_points", "stage": "VALIDATING",
        "approved": False, "prospective_samples": 0,
    }]
    assert all(s["joint_probability_calibration"] == "NOT_VERIFIED"
               for s in payload["sports"])
    assert "SECRET_DO_NOT_EXPOSE" not in response.body.decode()
    assert "baseball_mlb" not in response.body.decode()


def test_vip_boost_endpoint_does_not_require_paid_provider(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("VIP status must not perform paid provider calls")
    from jabazi.providers import balldontlie
    monkeypatch.setattr(balldontlie.BallDontLieProvider, "fetch", unexpected)
    monkeypatch.setattr(model_cache, "status", lambda loader: {
        "state": "READY", "data": {"models": []},
    })
    response = vip_api.boost_status(ctx=(object(), {"tier": "VIP"}))
    assert response.status_code == 200
