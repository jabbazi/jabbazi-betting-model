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


def test_lab_diagnostic_requires_private_authentication(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    client = TestClient(app)
    response = client.post("/v1/chatgpt/boost-lab-diagnostic",
                           json={"sport": "NBA", "slate_date": "2026-10-28"})
    assert response.status_code == 401


def test_lab_diagnostic_rejects_unsupported_nhl_model_type():
    client = TestClient(app)
    response = client.post("/v1/chatgpt/boost-lab-diagnostic",
                           json={"sport": "NHL", "slate_date": "2026-10-28"})
    assert response.status_code == 422


def test_lab_diagnostic_aggregate_only_never_returns_licensed_rows(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings
    from jabazi.vip import paid_models

    monkeypatch.setattr(chatgpt_api, "authorize", lambda authorization: None)
    monkeypatch.setattr(Settings, "from_environment",
                        lambda: SimpleNamespace(balldontlie_lab_api_key="lab-private"))
    calls = []
    def fake_reader(key, sport, day):
        calls.append((key, sport, day))
        return {"slate_date": "2026-10-28", "observed_at": "2026-10-28T18:00:00Z",
                "state": "RESEARCH_ONLY", "reason": None, "models_found": 1,
                "models_checked": 1, "predictions_seen": 1, "coverage_complete": True,
                "rows": [{"player_name": "SECRET_PLAYER", "model_signal_value": .92}],
                "rows_rejected_missing_identity_or_signal": 0}
    monkeypatch.setattr(paid_models, "read_paid_player_models", fake_reader)
    payload = boost_api.BoostLabRequest(sport="NBA", slate_date=date(2026, 10, 28))
    response = boost_api.diagnose_lab(payload, authorization="Bearer private")
    import json
    result = json.loads(response.body)
    assert calls == [("lab-private", "NBA", date(2026, 10, 28))]
    assert result["endpoint_authenticated"] is True
    assert result["saved_predictions_observed"] is True
    assert result["calibrated_exact_line_probabilities_verified"] is False
    assert result["betting_enabled"] is False
    assert "SECRET_PLAYER" not in response.body.decode()


def test_lab_diagnostic_requires_distinct_lab_key(monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    from fastapi import HTTPException
    import pytest
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings
    monkeypatch.setattr(chatgpt_api, "authorize", lambda authorization: None)
    monkeypatch.setattr(Settings, "from_environment",
                        lambda: SimpleNamespace(balldontlie_lab_api_key="",
                                                balldontlie_api_key="sports-only"))
    with pytest.raises(HTTPException) as exc:
        boost_api.diagnose_lab(
            boost_api.BoostLabRequest(sport="NFL", slate_date=date(2026, 10, 28)),
            authorization="Bearer private")
    assert exc.value.status_code == 503


def test_paid_join_requires_private_authentication(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    client = TestClient(app)
    result = client.post("/v1/chatgpt/boost-paid-join-diagnostic",
                         json={"sport": "NBA", "slate_date": "2026-10-28", "game_ids": [31]})
    assert result.status_code == 401


def test_paid_join_rejects_nhl_lab_and_duplicate_game_ids():
    client = TestClient(app)
    assert client.post("/v1/chatgpt/boost-paid-join-diagnostic",
        json={"sport": "NHL", "slate_date": "2026-10-28", "game_ids": [31]}).status_code == 422


def test_paid_join_missing_lab_credential_fails_before_sports_requests(monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    from fastapi import HTTPException
    import pytest
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings

    monkeypatch.setattr(chatgpt_api, "authorize", lambda token: None)
    monkeypatch.setattr(Settings, "from_environment",
        lambda: SimpleNamespace(balldontlie_api_key="sports", balldontlie_lab_api_key=""))
    request = boost_api.BoostJoinRequest(sport="NBA", slate_date=date(2026, 10, 28),
                                        game_ids=[31])
    with pytest.raises(HTTPException) as exc:
        boost_api.diagnose_join(request, authorization="Bearer private")
    assert exc.value.status_code == 503


def test_paid_join_empty_lab_skips_sports_api_calls(monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings
    from jabazi.vip import paid_models
    import json

    monkeypatch.setattr(chatgpt_api, "authorize", lambda token: None)
    monkeypatch.setattr(Settings, "from_environment",
        lambda: SimpleNamespace(balldontlie_api_key="sports", balldontlie_lab_api_key="lab"))
    monkeypatch.setattr(paid_models, "read_paid_player_models",
        lambda key, sport, day: {"coverage_complete": True,
            "state": "NO_PREDICTIONS", "reason": "NO_PREDICTIONS_ON_DATE", "rows": []})
    monkeypatch.setattr(boost_api, "BallDontLieProvider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sports should not be queried")))
    request = boost_api.BoostJoinRequest(sport="NBA", slate_date=date(2026, 10, 28),
                                        game_ids=[31])
    result = json.loads(boost_api.diagnose_join(request, authorization="Bearer private").body)
    assert result["status"] == "UNAVAILABLE"
    assert result["betting_enabled"] is False
    assert result["exact_identity_joins"] == 0


def test_goat_feed_diagnostic_requires_private_authentication(monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    response = TestClient(app).post("/v1/chatgpt/boost-goat-feed-diagnostic",
        json={"sport": "NHL", "slate_date": "2026-10-28", "max_games": 2})
    assert response.status_code == 401


def test_goat_feed_uses_sports_key_without_lab(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    import json
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings
    from tools import boost_live_acceptance

    monkeypatch.setattr(chatgpt_api, "authorize", lambda authorization: None)
    monkeypatch.setattr(Settings, "from_environment", lambda:
        SimpleNamespace(balldontlie_api_key="goat-sports-only", balldontlie_lab_api_key=""))
    calls = []
    class FakeProvider:
        def __init__(self, key, *, budget):
            calls.append((key, budget))
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(boost_api, "BallDontLieProvider", FakeProvider)
    def fake_audit(provider, *, sport, calendar_date, max_games):
        assert sport == "NHL"
        assert calendar_date == date(2026, 10, 28)
        assert max_games == 2
        return {
            "coverage": "FULL", "games_eligible": 1,
            "games_with_eligible_quotes": 1, "eligible_quote_rows": 12,
            "observed_market_breadth": {"market_types_seen": 2, "markets": {}},
            "errors": [],
        }
    monkeypatch.setattr(boost_live_acceptance, "audit_sport", fake_audit)
    result = boost_api.diagnose_goat(
        boost_api.GoatSportFeedRequest(sport="NHL", slate_date=date(2026, 10, 28),
                                      max_games=2),
        authorization="Bearer private")
    data = json.loads(result.body)
    assert data["source"] == "BALLDONTLIE_SPORTS_API"
    assert data["lab_required"] is False
    assert data["status"] == "RESEARCH_ONLY"
    assert data["jabbazi_exact_line_probabilities_verified"] is False
    assert data["joint_probability_validated"] is False
    assert data["betting_enabled"] is False
    assert data["production_approved"] is False
    assert calls == [("goat-sports-only", 20), "closed"]


def test_goat_feed_missing_sports_key_fails_closed(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from jabazi import boost_api, chatgpt_api
    from jabazi.config import Settings
    monkeypatch.setattr(chatgpt_api, "authorize", lambda authorization: None)
    monkeypatch.setattr(Settings, "from_environment", lambda:
        SimpleNamespace(balldontlie_api_key="", balldontlie_lab_api_key="lab-key"))
    with pytest.raises(HTTPException) as exc:
        boost_api.diagnose_goat(
            boost_api.GoatSportFeedRequest(sport="NBA", slate_date=date(2026, 10, 28)),
            authorization="Bearer private")
    assert exc.value.status_code == 503


def test_goat_feed_rejects_out_of_scope_sport():
    response = TestClient(app).post("/v1/chatgpt/boost-goat-feed-diagnostic",
        json={"sport": "MLB", "slate_date": "2026-10-28"})
    assert response.status_code == 422
