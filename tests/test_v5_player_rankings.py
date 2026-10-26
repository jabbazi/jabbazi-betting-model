"""V5 player research ranking contracts: no fabricated approval or duplicate Top 10 entries."""
from datetime import UTC, datetime, timedelta

from jabazi.vip.rankings import research_hub

NOW = datetime(2026, 10, 26, 16, tzinfo=UTC)


def player_row(**changes):
    base = {
        "id": "row-1", "sport": "NFL", "event_id": "game-1",
        "event": "Away @ Home", "starts_at": (NOW + timedelta(hours=4)).isoformat(),
        "price_at": NOW.isoformat(), "lifecycle": "UPCOMING", "status": "WATCH",
        "fresh": True, "data_health": "HEALTHY", "market": "player_anytime_td",
        "player": "Player One", "selection": "Yes", "line": None,
        "decimal": 2.4, "market_probability": .4,
        "model_probability": .5, "model_stage": "VALIDATING",
        "model_version": "nfl-research-v5",
    }
    return {**base, **changes}


def test_validating_player_model_is_research_only_not_value():
    result = research_hub([player_row()], sport="NFL", now=NOW)
    assert len(result["anytime_td"]) == 1
    assert result["anytime_td"][0]["evidence_label"] == "SHADOW MODEL"
    assert result["anytime_td"][0]["approved_for_betting"] is False
    assert result["anytime_td_value"] == []
    assert result["player_market_value"]["player_anytime_td"] == []


def test_per_market_top10_deduplicates_players_and_keeps_exact_line():
    rows = [
        player_row(id="lower", market="player_reception_yds", player="Receiver",
                   selection="Over", line=64.5, model_probability=.61),
        player_row(id="higher", market="player_reception_yds", player="Receiver",
                   selection="Over", line=74.5, model_probability=.59),
        player_row(id="other", market="player_reception_yds", player="Other",
                   selection="Over", line=50.5, model_probability=.55),
    ]
    result = research_hub(rows, sport="NFL", now=NOW)
    ranked = result["player_markets"]["player_reception_yds"]
    assert len(ranked) == 2
    assert ranked[0]["player"] == "Receiver"
    assert ranked[0]["line"] == 64.5
    assert len(result["receiving_overs"]) == 3  # exact-line research remains available


def test_approved_value_separate_from_probability_and_shadow():
    approved = player_row(id="approved", sport="NBA", market="player_points",
                          model_stage="PRODUCTION_APPROVED", model_probability=.6,
                          decimal=2.0, player="NBA Player")
    shadow = player_row(id="shadow", sport="NBA", market="player_points",
                        model_stage="SHADOW_ONLY", model_probability=.8,
                        decimal=2.0, player="Other NBA Player")
    result = research_hub([approved, shadow], sport="NBA", now=NOW)
    assert len(result["player_markets"]["player_points"]) == 2
    value = result["player_market_value"]["player_points"]
    assert len(value) == 1
    assert value[0]["player"] == "NBA Player"
    assert value[0]["ev"] > 0


def test_stale_and_unhealthy_never_populate_player_rankings():
    rows = [
        player_row(id="stale", price_at=(NOW-timedelta(minutes=7)).isoformat()),
        player_row(id="unhealthy", player="Other", data_health="DEGRADED"),
        player_row(id="quarantined", player="Third", model_stage="QUARANTINED"),
    ]
    result = research_hub(rows, sport="NFL", now=NOW)
    assert not result["anytime_td"]
    assert not result["player_markets"]


def test_no_cfb_player_market_and_no_first_td_mislabeled_as_anytime():
    rows = [
        player_row(id="first", market="player_first_td"),
        player_row(id="cfb", sport="CFB", market="player_anytime_td"),
    ]
    result = research_hub(rows, now=NOW)
    assert not result["anytime_td"]
    assert not result["player_markets"]
