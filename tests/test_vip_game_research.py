"""Game-center safety tests: research projections are not betting approval."""
from datetime import UTC, datetime, timedelta
import pytest
from test_member_portal import portal as _portal_fixture

portal = _portal_fixture

from jabazi.vip.game_research import (
    matchups, matchup_detail, simulate_samples, first_td_distribution,
)


def _row(selection, probability, market_probability, *, sport="NFL", event_id="g1", market="h2h"):
    return {
        "sport": sport, "event_id": event_id, "event": "Away @ Home",
        "starts_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "lifecycle": "UPCOMING", "market": market, "selection": selection,
        "model_probability": probability, "model_version": "synthetic-test" if probability else None,
        "market_probability": market_probability, "fresh": True,
        "price_at": datetime.now(UTC).isoformat(),
    }


def test_matchups_are_deduped_and_projection_provenance_preserved():
    rows = [_row("Home", 0.61, 0.55), _row("Away", 0.39, 0.45),
            _row("Over", None, None, market="totals")]
    games = matchups(rows)
    assert len(games) == 1
    assert games[0]["observed_rows"] == 3
    detail = matchup_detail(rows, "NFL", "g1")
    assert detail["projection"]["selection"] == "Home"
    assert detail["projection"]["model_probability"] == pytest.approx(.61)
    assert detail["projection"]["betting_status"] == "RESEARCH ONLY"
    assert detail["simulation"]["state"] == "UNAVAILABLE"
    assert detail["first_td"]["state"] == "SHADOW_ONLY"


def test_market_fallback_does_not_create_fake_model_probability():
    rows = [_row("Home", None, .56), _row("Away", None, .44)]
    projection = matchup_detail(rows, "NFL", "g1")["projection"]
    assert projection["source"] == "MARKET CONSENSUS"
    assert projection["model_probability"] is None


def test_simulation_only_summarizes_real_supplied_score_samples():
    samples = [(24, 17)] * 70 + [(17, 24)] * 30
    result = simulate_samples(samples, home="Home", away="Away", spread_line=-3.5, total_line=40.5)
    assert result["home_win"]["win"] == pytest.approx(.7)
    assert result["summary"]["sample_count"] == 100
    assert result["approved_for_betting"] is False
    with pytest.raises(ValueError):
        simulate_samples([(1, 0)] * 5, home="Home", away="Away")


def test_first_td_distribution_requires_complete_coherent_outcomes():
    d = first_td_distribution(
        team_first_td_probabilities={"Home": .55, "Away": .40},
        scorer_shares={
            "Home": {"Runner": .6, "Other/Defense": .4},
            "Away": {"Receiver": .5, "Other/Defense": .5},
        },
        no_td_probability=.05,
    )
    assert sum(x["probability"] for x in d["outcomes"]) + d["no_td_probability"] == pytest.approx(1)
    assert d["approved_for_betting"] is False
    with pytest.raises(ValueError):
        first_td_distribution(
            team_first_td_probabilities={"Home": .6, "Away": .5},
            scorer_shares={"Home": {"A": 1}, "Away": {"B": 1}},
            no_td_probability=0,
        )


def test_vip_matchup_endpoints_require_member_and_fail_closed(portal):
    from test_member_portal import sign_in
    store, client = portal
    assert client.get("/v1/vip/matchups").status_code == 401
    sign_in(store, client)
    assert client.get("/v1/vip/matchups").status_code == 200
    assert client.get("/v1/vip/matchup/NFL/unknown").status_code == 404
    assert client.get("/v1/vip/sim/NFL/unknown").status_code == 404
    assert client.get("/v1/vip/firsttd/unknown").status_code == 404
