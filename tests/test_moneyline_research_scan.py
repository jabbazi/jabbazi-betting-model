"""Preserve independent team model research in the full scanner response."""
from jabazi.player_probability_board import moneyline_research_from_scan


def row(**changes):
    result = {
        "sport": "basketball_nba", "event_id": "game-1", "event": "A @ B",
        "market": "h2h", "selection": "A",
        "model_probability": ".62",
        "model_version": "team-v1", "probability_status": "VALIDATING",
        "price_is_current": True,
    }
    result.update(changes)
    return result


def test_moneyline_summary_uses_versioned_model_probability_only():
    rows = [
        row(),
        row(selection="B", model_probability=".47"),
        row(selection="A", model_probability=".59"),
        row(sport="americanfootball_nfl", event_id="game-2",
            selection="C", model_probability=".72"),
        row(selection="D", model_probability=None, consensus_probability=".95"),
        row(selection="E", model_version=None, model_probability=".94"),
        row(selection="F", price_is_current=False, model_probability=".91"),
        row(selection="G", model_probability=".93", probability_status="UNAVAILABLE"),
        row(selection="H", model_probability="nan"),
        row(selection="I", market="player_points", model_probability=".99"),
    ]
    report = moneyline_research_from_scan(rows, present=lambda item: item)
    nba = report["sports"]["NBA"]
    assert nba["observed_moneyline_rows"] == 8
    assert nba["model_estimate_rows"] == 3
    assert [x["selection"] for x in nba["top10"]] == ["A", "B"]
    assert nba["top10"][0]["model_probability"] == .62
    assert nba["top10"][0]["approved_for_betting"] is False
    assert report["sports"]["NFL"]["returned"] == 1
    assert report["sports"]["NHL"]["status"] == "NO_MONEYLINE_ROWS"
    assert report["betting_enabled"] is False
