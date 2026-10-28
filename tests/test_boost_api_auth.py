"""Read-only boost research endpoint tests (no vendor calls)."""
from fastapi.testclient import TestClient
from jabazi.api import app


def test_boost_diagnostic_requires_authentication(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    client = TestClient(app)
    response = client.post("/v1/chatgpt/boost-feed-diagnostic",
                           json={"sport": "NHL", "game_ids": [123]})
    assert response.status_code == 401


def test_boost_diagnostic_rejects_unknown_sport():
    client = TestClient(app)
    response = client.post("/v1/chatgpt/boost-feed-diagnostic",
                           json={"sport": "MLB", "game_ids": [123]})
    assert response.status_code == 422
