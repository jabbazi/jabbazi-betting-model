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
        "model_stage": "SHADOW_ONLY", "data_health": "HEALTHY", "status": "WATCH",
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
    assert detail["first_td"]["state"] == "UNAVAILABLE"


@pytest.mark.parametrize("changes", [{"model_stage": "QUARANTINED"},
                                    {"status": "QUARANTINED"},
                                    {"data_health": "DEGRADED"},
                                    {"model_stage": "UNAVAILABLE"}])
def test_blocked_model_never_leaks_into_market_fallback(changes):
    rows = [{**_row("Home", .99, .56), **changes}]
    projection = matchup_detail(rows, "NFL", "g1")["projection"]
    assert projection["source"] == "MARKET CONSENSUS"
    assert projection["model_probability"] is None
    assert projection["model_version"] is None
    assert matchups(rows)[0]["model_supported_rows"] == 0


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


def test_graphic_requires_approved_logo_and_uses_exact_asset(tmp_path):
    from io import BytesIO
    from PIL import Image
    from jabazi.vip.graphics import render_matchup
    detail = {"sport": "NFL", "event": "Away @ Home",
              "projection": {"selection": "Home", "source": "INDEPENDENT MODEL",
                             "model_probability": .61}}
    with pytest.raises(FileNotFoundError):
        render_matchup(detail, tmp_path / "missing.png")
    logo = tmp_path / "approved.png"
    Image.new("RGB", (320, 160), (255, 10, 138)).save(logo)
    graphic = Image.open(BytesIO(render_matchup(detail, logo)))
    assert graphic.size == (1200, 675)


def test_play_of_day_is_not_forced(portal):
    from test_member_portal import sign_in
    store, client = portal
    assert client.get("/v1/vip/playoftheday").status_code == 401
    sign_in(store, client)
    payload = client.get("/v1/vip/playoftheday").json()
    assert payload["state"] == "PASS"
    assert payload["play"] is None


def test_real_score_adapter_preserves_pushes_and_quarantine():
    from test_score_models import artifact, card
    from jabazi.vip.game_research import simulate_current_event
    a = artifact()
    price = card(a)
    class Store:
        def list_records(self, *args, **kwargs):
            return [{"payload": a}]
    row = {**_row(price.selection, None, .5), "event_id": price.event_id,
           "event": price.event, "price_at": price.observed_at.isoformat(),
           "starts_at": price.starts_at.isoformat(), "decimal": 2, "book": "TEST"}
    result = simulate_current_event(Store(), sport="NFL", event_id=price.event_id,
                                    rows=[row], spread_line=0, total_line=44)
    assert result["state"] == "SHADOW_ONLY"
    assert result["spread"]["win"] == result["home_win"]["win"]
    assert result["spread"]["push"] == result["home_win"]["push"]
    assert sum(result["total"][k] for k in ("win", "loss", "push")) == pytest.approx(1)
    a["status"] = "QUARANTINED"
    blocked = simulate_current_event(Store(), sport="NFL", event_id=price.event_id, rows=[row])
    assert blocked["state"] == "QUARANTINED"
    assert "summary" not in blocked


@pytest.mark.parametrize("changes", [
    {"status": "QUARANTINED"},
    {"status": "INVALIDATED"},
    {"data_health": "DEGRADED"},
    {"lifecycle": "LIVE"},
    {"lifecycle": "HISTORICAL"},
    {"model_stage": "QUARANTINED"},
])
def test_score_simulation_rejects_untrusted_market_context(changes):
    from test_score_models import artifact, card
    from jabazi.vip.game_research import simulate_current_event
    a = artifact()
    p = card(a)
    class Store:
        def list_records(self, *args, **kwargs):
            return [{"payload": a}]
    row = {**_row(p.selection, None, .5), "event_id": p.event_id,
           "event": p.event, "price_at": p.observed_at.isoformat(),
           "starts_at": p.starts_at.isoformat(), "decimal": 2, "book": "TEST",
           **changes}
    result = simulate_current_event(Store(), sport="NFL", event_id=p.event_id, rows=[row])
    assert result["state"] == "UNAVAILABLE"
    assert result["approved_for_betting"] is False
    assert "summary" not in result


@pytest.mark.parametrize("query", ["spread_line=nan", "total_line=inf", "total_line=-1", "spread_line=301"])
def test_scenario_endpoint_rejects_invalid_lines(portal, query):
    from test_member_portal import sign_in
    store, client = portal
    sign_in(store, client)
    assert client.get('/v1/vip/sim/NFL/g1?' + query).status_code == 422


def test_nhl_adapter_uses_canonical_weighted_grid_and_blocks_stale_state():
    from test_nhl import artifact, card
    from jabazi.vip.game_research import simulate_current_event
    from jabazi.models.nhl_goals import NHLGoalsModel
    a = artifact()
    p = card(a)
    class Store:
        def list_records(self, *args, **kwargs):
            return [{"payload": a}]
    row = {**_row(p.selection, None, .5), "sport": "NHL", "event_id": p.event_id,
           "event": p.event, "price_at": p.observed_at.isoformat(),
           "starts_at": p.starts_at.isoformat(), "decimal": 2, "book": "TEST"}
    result = simulate_current_event(Store(), sport="NHL", event_id=p.event_id,
                                    rows=[row], spread_line=-1, total_line=6)
    assert result["state"] == "SHADOW_ONLY"
    assert result["home_win"]["push"] == 0
    assert result["summary"]["count_label"] == "Weighted score outcomes"
    assert result["home_win"]["win"] == pytest.approx(float(NHLGoalsModel(a).estimate(p).probability))
    for market in ("spread", "total"):
        assert sum(result[market][k] for k in ("win", "loss", "push")) == pytest.approx(1)
        assert result[market]["push"] > 0
    a["state_refreshed_at"] = "2000-01-01T00:00:00+00:00"
    assert simulate_current_event(Store(), sport="NHL", event_id=p.event_id, rows=[row])["state"] == "UNAVAILABLE"
    a["status"] = "QUARANTINED"
    with pytest.raises(ValueError):
        NHLGoalsModel(a)


def test_graphics_auth_and_unavailable_simulation(portal, monkeypatch):
    from test_member_portal import sign_in
    import jabazi.vip.api as api
    store, client = portal
    monkeypatch.setattr(api, 'snapshot', lambda store: {'rows': [_row('Home', .61, .55)], 'snapshot_at': 'TEST'})
    assert client.get('/v1/vip/graphic/NFL/g1').status_code == 401
    sign_in(store, client)
    response = client.get('/v1/vip/graphic/NFL/g1')
    assert response.status_code == 200
    assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
    assert 'no-store' in response.headers['cache-control']
    assert client.get('/v1/vip/graphic/NFL/g1?kind=simulation').status_code == 503
    assert client.get('/v1/vip/graphic/NFL/g1?kind=cheatsheet&day=2000-01-01').status_code == 404
    assert client.get('/vip/jabbazi-approved.png').status_code == 200
    assert client.get('/v1/vip/performance-graphic').status_code == 503


def test_daily_rankings_requires_membership_and_returns_scoped_contract(portal):
    from test_member_portal import sign_in
    store, client = portal
    assert client.get('/v1/vip/rankings?sport=NFL').status_code == 401
    sign_in(store, client)
    response = client.get('/v1/vip/rankings?sport=NFL')
    assert response.status_code == 200
    body = response.json()
    assert body['sport'] == 'NFL'
    assert body['timezone'] == 'America/Chicago'
    assert len(body['anytime_td']) <= 10
    assert body['receiving_totals'] == []


def test_matchup_explanation_matches_evidence_and_does_not_invent_team_context():
    d = matchup_detail([_row('Home', .61, .55), _row('Away', .39, .45)], 'NFL', 'g1')
    reason = d['pick_explanation']
    assert '61%' in reason['reason'] and '55%' in reason['reason']
    assert 'still being evaluated' in reason['caution']
    assert reason['observed_at']
    d = matchup_detail([_row('Home', None, .56)], 'NFL', 'g1')
    assert 'market favors Home' in d['pick_explanation']['reason']
    assert 'not an independent model' in d['pick_explanation']['caution']
    d = matchup_detail([{**_row('Home', .9, .56), 'fresh':False}], 'NFL', 'g1')
    assert 'No fresh' in d['pick_explanation']['reason']


def test_reviewed_pick_explanation_remains_qualitative():
    from jabazi.vip.game_research import projection_reason
    explanation = projection_reason({'selection':'Home'}, evidence={'source':'Reviewed publisher', 'retrieved_at':'2026-10-13T17:00:00Z'})
    assert explanation['reason'] == 'Reviewed publisher supports Home in the current reviewed research.'
    assert 'probability and betting edge are unavailable' in explanation['caution']


def test_api_11pm_default_and_explicit_current_day(portal):
    import time_machine
    from test_member_portal import sign_in
    store, client = portal
    with time_machine.travel('2026-10-14T04:10:00Z', tick=False):
        sign_in(store, client)
        rows = [{'sport':'baseball_mlb', 'event_id':event, 'event':'Away @ Home',
                 'market':'h2h','selection':'Home','starts_at_utc':start,
                 'price_time_utc':'2026-10-14T04:10:00Z','decimal_odds':2,
                 'market_no_vig_probability':.6,'executable':True}
                for event,start in [('tonight','2026-10-14T04:45:00Z'),('tomorrow','2026-10-14T20:00:00Z')]]
        store.append('research_sheet','latest_scan',{'healthy':True,'completed_at':'2026-10-14T04:10:00Z','rows':rows,'slate_events':rows})
        automatic = client.get('/v1/vip/board?sport=MLB').json()
        assert automatic['date'] == '2026-10-14'
        assert [r['event_id'] for r in automatic['rows']] == ['tomorrow']
        current = client.get('/v1/vip/board?sport=MLB&slate_date=2026-10-13').json()
        assert [r['event_id'] for r in current['rows']] == ['tonight']
        rankings = client.get('/v1/vip/rankings?sport=MLB').json()
        assert [r['event_id'] for r in rankings['moneyline_likely']] == ['tomorrow']
        assert client.get('/v1/vip/board?slate_date=invalid').status_code == 422
