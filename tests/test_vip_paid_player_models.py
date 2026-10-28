"""Read-only paid LAB player feed tests: never invent hit probabilities."""
import json

import httpx
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.vip.paid_models import read_paid_player_models
from jabazi.vip import api as vip_api
from datetime import date


DAY = date(2026, 10, 28)


def _transport(status=200, *, missing_player_id=False, bad_cursor=False):
    paths = []

    def send(request):
        assert request.headers.get("Authorization") == "existing-private-key"
        assert request.method == "GET"
        paths.append((request.url.path, dict(request.url.params)))
        if status != 200:
            return httpx.Response(status, json={"detail": "SECRET PRIVATE MESSAGE"})
        if request.url.path == "/lab/v1/models":
            return httpx.Response(200, json={
                "data": [
                    {"id": 11, "name": "Points", "sport": "nba",
                     "model_type": "player_prop", "prop_type": "points"},
                    {"id": 12, "name": "Game ML", "sport": "nba",
                     "model_type": "game", "prop_type": None},
                ], "meta": {},
            })
        if request.url.path == "/lab/v1/predictions":
            assert request.url.params["model_id"] == "11"
            assert request.url.params["start_date"] == "2026-10-28"
            assert request.url.params["end_date"] == "2026-10-29"
            response = {
                "data": [{"id": 71, "model_id": 11, "player_id": None if missing_player_id else 8,
                          "game_id": 31, "predicted_value": 27.2,
                          "confidence": .98, "predicted_side": "over", "market_value": 26.5,
                          "extra_licensed_field": "KEEP_PRIVATE"}],
                "meta": {"next_cursor": "1"} if bad_cursor else {},
            }
            return httpx.Response(200, json=response)
        raise AssertionError("Unexpected endpoint")
    return httpx.MockTransport(send), paths


def test_only_nba_saved_player_models_and_bounded_read():
    transport, paths = _transport()
    report = read_paid_player_models("existing-private-key", "NBA", DAY, transport=transport)
    assert [p for p, _ in paths] == ["/lab/v1/models", "/lab/v1/predictions"]
    assert report["coverage_complete"] is True
    assert report["models_found"] == 1 and report["models_checked"] == 1
    assert report["state"] == "RESEARCH_ONLY"
    assert report["rows"][0]["predicted_value"] == 27.2
    assert report["rows"][0]["model_signal_value"] == 27.2
    assert report["rows"][0]["stat_total_projection"] is None
    assert report["rows"][0]["stat_total_projection_verified"] is False
    assert report["rows"][0]["model_hit_probability"] is None
    assert report["rows"][0]["provider_confidence_raw"] == .98
    assert "extra_licensed_field" not in json.dumps(report)
    assert report["betting_enabled"] is False


def test_missing_entitlement_fails_closed_and_redacts_provider_body():
    transport, paths = _transport(403)
    report = read_paid_player_models("existing-private-key", "NFL", DAY, transport=transport)
    assert report["state"] == "UNAVAILABLE"
    assert report["reason"] == "LAB_ACCESS_DENIED"
    assert report["rows"] == []
    assert "SECRET" not in json.dumps(report)
    assert len(paths) == 1


def test_missing_key_makes_zero_external_requests():
    report = read_paid_player_models("", "NBA", DAY)
    assert report["state"] == "UNAVAILABLE"
    assert report["reason"] == "NO_CREDENTIAL"
    assert report["rows"] == []


def test_nhl_player_prop_lab_not_supported_and_does_not_call_provider():
    transport, paths = _transport()
    report = read_paid_player_models("existing-private-key", "NHL", DAY, transport=transport)
    assert paths == []
    assert report["state"] == "UNAVAILABLE"
    assert report["reason"] == "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
    assert report["source_player_prop_supported"] is False
    assert report["rows"] == []
    assert report["betting_enabled"] is False


def test_paginated_duplicate_cursor_blocks_partial_as_complete():
    transport, paths = _transport(bad_cursor=True)
    report = read_paid_player_models("existing-private-key", "NBA", DAY, transport=transport)
    assert report["state"] == "UNAVAILABLE"
    assert report["reason"] == "LAB_BAD_CURSOR"
    assert report["rows"] == []
    assert len(paths) == 3


def test_research_result_without_player_identity_does_not_claim_join():
    transport, paths = _transport(missing_player_id=True)
    report = read_paid_player_models("existing-private-key", "NBA", DAY, transport=transport)
    assert report["rows"][0]["player_id"] is None
    assert report["rows"][0]["hit_probability_verified"] is False


def test_vip_paid_models_endpoint_requires_session():
    response = TestClient(app).get("/v1/vip/paid-player-models?sport=NBA")
    assert response.status_code in {401, 503}
    assert response.status_code != 200


def test_vip_paid_models_endpoint_is_read_only_and_sport_isolated(monkeypatch):
    called = []
    from jabazi.vip import paid_models

    def fake_reader(key, sport, day):
        called.append((key, sport, day))
        return {"sport": sport, "rows": [], "betting_enabled": False}

    monkeypatch.setattr(paid_models, "read_paid_player_models", fake_reader)
    monkeypatch.setenv("JABBAZI_BALLDONTLIE_API_KEY", "existing-private-key")
    class Store:
        vip_slate_date = DAY
    value = vip_api.paid_player_models(sport="NHL", ctx=(Store(), {"tier": "VIP"}))
    assert json.loads(value.body)["sport"] == "NHL"
    assert called == [("existing-private-key", "NHL", DAY)]



def test_paid_lab_operator_summary_never_leaks_rows_or_signals():
    from tools.verify_paid_lab_access import summarized

    record = {
        "sport": "NBA", "slate_date": "2026-10-28",
        "observed_at": "2026-10-28T10:00:00+00:00",
        "state": "RESEARCH_ONLY", "reason": None,
        "source_player_prop_supported": True, "models_found": 1,
        "models_checked": 1, "predictions_seen": 1,
        "rows": [{"player_name": "PRIVATE", "model_signal_value": 1.2,
                  "model_hit_probability": 0.99, "provider_key": "DO_NOT_LEAK"}],
        "coverage_complete": True,
    }
    result = summarized(record)
    assert result["visible_research_rows"] == 1
    assert result["model_hit_probabilities_verified"] is False
    assert result["betting_enabled"] is False
    assert "PRIVATE" not in json.dumps(result)
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert "0.99" not in json.dumps(result)


def test_paid_lab_operator_command_fails_when_nba_access_unverified(monkeypatch, capsys):
    from tools import verify_paid_lab_access as probe
    from types import SimpleNamespace

    monkeypatch.setattr(
        probe.Settings, "from_environment",
        lambda: SimpleNamespace(balldontlie_api_key="existing-private-key"),
    )
    monkeypatch.setattr(
        probe, "read_paid_player_models",
        lambda key, sport, day: {
            "sport": sport, "slate_date": day.isoformat(),
            "observed_at": "2026-10-28T10:00:00+00:00",
            "state": "UNAVAILABLE", "reason": "LAB_ACCESS_DENIED",
            "source_player_prop_supported": True, "models_found": 0,
            "models_checked": 0, "predictions_seen": 0,
            "rows": [], "coverage_complete": False,
        },
    )
    assert probe.main(["--sport", "NBA", "--date", "2026-10-28"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["release_approved"] is False
    assert output["paid_player_hit_probabilities_verified"] is False
    assert output["results"][0]["reason"] == "LAB_ACCESS_DENIED"
