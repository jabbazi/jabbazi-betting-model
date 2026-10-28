"""End-to-end authenticated diagnostic integration, using a mock provider only."""
from fastapi.testclient import TestClient
from jabazi.api import app
from jabazi import boost_api
from jabazi.boost_feed import BoostFeedReport
from jabazi.chatgpt_api import scanner_key


def test_authenticated_nhl_diagnostic_never_queries_other_sports(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    monkeypatch.setenv("JABBAZI_BALLDONTLIE_API_KEY", "fake-test-key")
    requested = []

    class FakeProvider:
        def __init__(self, key, **kwargs):
            assert key == "fake-test-key"
        def fetch_all_pages(self, sport, resource, params, **kwargs):
            requested.append((sport, resource, tuple(params)))
            return {"complete": True, "pages": 1,
                    "data": [{"id": 1, "licensed": "not-to-expose"}]}
        def close(self):
            pass

    monkeypatch.setattr(boost_api, "BallDontLieProvider", FakeProvider)
    client = TestClient(app)
    response = client.post(
        "/v1/chatgpt/boost-feed-diagnostic",
        json={"sport": "NHL", "game_ids": [123]},
        headers={"Authorization": "Bearer " + scanner_key()},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sport"] == "NHL"
    assert payload["coverage"] == "FULL"
    assert payload["odds_rows"] == 1
    assert payload["player_probabilities_verified"] is False
    assert payload["wager_recommendation"] == "UNAVAILABLE"
    assert "licensed" not in response.text
    assert requested == [("nhl", "props", (("game_id", 123),))]
