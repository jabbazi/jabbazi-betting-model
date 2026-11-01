"""Model-only probability boards must never fabricate hit chances or bets."""
import json

from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.player_probability_board import from_scan_actions, from_vip_board
from jabazi.vip import api as vip_api


def scan_action(**changes):
    return {
        "sport": "basketball_nba", "event_id": "game-1",
        "event": "Away @ Home", "market": "player_points",
        "participant": "Player A", "selection": "over", "line": 24.5,
        "source_timestamp": "2026-10-31T18:00:00Z",
        "starts_at": "2026-10-31T23:00:00Z",
        "model_version": "nba-model-v1", "model_probability": ".62",
        "probability_status": "VALIDATING", "price_is_current": True,
        **changes,
    }


def test_scan_summary_is_model_only_and_does_not_confuse_market_odds():
    rows = [
        scan_action(),
        scan_action(participant="Player B", model_probability=".73"),
        scan_action(participant="Player B", model_probability=".69", line=25.5),
        scan_action(participant="Player C", model_probability=None,
                    consensus_probability=".95", model_version=None),
        scan_action(participant="Player D", model_probability=".97",
                    price_is_current=False),
        scan_action(participant="Player E", model_probability="nan"),
        scan_action(sport="icehockey_nhl", market="player_goals",
                    participant="Player F", model_probability=".44",
                    model_version="nhl-v1"),
    ]
    # Serializer supplies the freshness/provenance gates, not a market-only proxy.
    report = from_scan_actions(rows, present=lambda r: r)
    nba = report["sports"]["NBA"]
    assert nba["observed_player_market_rows"] == 6
    assert nba["model_estimate_rows"] == 3
    assert [r["player"] for r in nba["top10"]] == ["Player B", "Player A"]
    assert nba["top10"][0]["model_probability"] == .73
    assert nba["status"] == "RESEARCH_ESTIMATES_AVAILABLE"
    assert report["sports"]["NFL"]["status"] == "NO_PLAYER_MARKET_ROWS"
    assert report["sports"]["NHL"]["returned"] == 1
    assert report["paid_requests_made"] == 0
    assert report["betting_enabled"] is False
    assert all(r["approved_for_betting"] is False for r in nba["top10"])
    assert "Player C" not in json.dumps(report)
    assert ".95" not in json.dumps(report)


def test_scan_summary_with_missing_or_stale_models_is_explicitly_unavailable():
    rows = [
        scan_action(model_version=None),
        scan_action(participant="Player B", probability_status="UNAVAILABLE"),
        scan_action(participant="Player C", price_is_current=False),
        scan_action(participant="Player D", model_probability="1.0"),
    ]
    report = from_scan_actions(rows, present=lambda r: r)
    nba = report["sports"]["NBA"]
    assert nba["observed_player_market_rows"] == 4
    assert nba["model_estimate_rows"] == 0
    assert nba["top10"] == []
    assert nba["status"] == "NO_VALID_MODEL_PROBABILITIES"


def vip_row(**changes):
    return {
        "sport": "NBA", "event_id": "event-1", "event": "Away @ Home",
        "player": "Player A", "market": "player_points",
        "selection": "over", "line": 20.5, "model_probability": .61,
        "market_probability": .79, "model_version": "nba-model-v1",
        "model_stage": "VALIDATING", "fresh": True, "data_health": "HEALTHY",
        "status": "WATCH", "starts_at": "2026-10-31T23:00:00Z",
        "price_at": "2026-10-31T18:00:00Z",
        **changes,
    }


def test_vip_summary_exposes_validating_models_without_upgrading_approval():
    rows = [
        vip_row(),
        vip_row(player="Player B", model_probability=None, market_probability=.99),
        vip_row(player="Player C", model_probability=.80, fresh=False),
        vip_row(player="Player D", model_probability=.77, data_health="UNKNOWN"),
        vip_row(player="Player E", model_probability=.76, status="QUARANTINED"),
        vip_row(player="Player F", model_probability=.74, model_version=None),
        vip_row(player="Player G", model_probability=.70, model_stage="NO_MODEL"),
        vip_row(player="Player H", model_probability=.69, sport="NFL"),
    ]
    report = from_vip_board(rows, sport="NBA")
    assert report["observed_player_market_rows"] == 7
    assert report["model_estimate_rows"] == 1
    assert [r["player"] for r in report["top10"]] == ["Player A"]
    assert report["top10"][0]["model_probability"] == .61
    assert report["top10"][0]["model_stage"] == "VALIDATING"
    assert report["top10"][0]["approved_for_betting"] is False
    assert report["betting_enabled"] is False
    assert report["paid_requests_made"] == 0


def test_vip_route_reuses_snapshot_and_does_not_call_paid_provider(monkeypatch):
    def fake_snapshot(store):
        return {
            "rows": [vip_row()],
            "state": "HEALTHY",
            "snapshot_at": "2026-10-31T18:00:00Z",
            "date": "2026-10-31",
        }
    monkeypatch.setattr(vip_api, "snapshot", fake_snapshot)
    class Store:
        pass
    response = vip_api.player_probabilities(
        sport="NBA", ctx=(Store(), {"tier": "VIP"})
    )
    data = json.loads(response.body)
    assert data["sport"] == "NBA"
    assert data["status"] == "RESEARCH_ESTIMATES_AVAILABLE"
    assert data["returned"] == 1
    assert data["top10"][0]["approved_for_betting"] is False
    assert data["snapshot_at"] == "2026-10-31T18:00:00Z"


def test_vip_route_rejects_unauthenticated_access():
    response = TestClient(app).get("/v1/vip/player-probabilities?sport=NBA")
    assert response.status_code in {401, 503}
    assert response.status_code != 200
