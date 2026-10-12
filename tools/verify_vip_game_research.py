"""Read-only deterministic verification for VIP game research calculations."""
import json
from datetime import UTC, datetime, timedelta
from jabazi.vip.game_research import matchups, matchup_detail, simulate_samples, first_td_distribution


def main():
    now = datetime.now(UTC)
    common = {
        "sport": "NFL", "event_id": "synthetic-event", "event": "Away @ Home",
        "starts_at": (now + timedelta(hours=3)).isoformat(),
        "lifecycle": "UPCOMING", "market": "h2h", "fresh": True,
        "model_stage": "SHADOW_ONLY", "data_health": "HEALTHY", "status": "WATCH",
        "price_at": now.isoformat(),
    }
    rows = [
        {**common, "selection": "Home", "model_probability": .61,
         "market_probability": .56, "model_version": "synthetic-verification"},
        {**common, "selection": "Away", "model_probability": .39,
         "market_probability": .44, "model_version": "synthetic-verification"},
    ]
    assert len(matchups(rows)) == 1
    detail = matchup_detail(rows, "NFL", "synthetic-event")
    assert detail["projection"]["selection"] == "Home"
    assert detail["projection"]["betting_status"] == "RESEARCH ONLY"
    scores = simulate_samples([(24, 17)] * 70 + [(17, 24)] * 30, home="Home", away="Away")
    assert abs(scores["home_win"]["win"] - .7) < 1e-9
    assert scores["approved_for_betting"] is False
    first = first_td_distribution(
        team_first_td_probabilities={"Home": .55, "Away": .40},
        scorer_shares={"Home": {"Runner": .6, "Other/Defense": .4},
                       "Away": {"Receiver": .5, "Other/Defense": .5}},
        no_td_probability=.05,
    )
    assert abs(sum(x["probability"] for x in first["outcomes"]) + first["no_td_probability"] - 1) < 1e-9
    assert first["approved_for_betting"] is False
    print("JABBAZI_VIP_GAME_RESEARCH_VERIFICATION " + json.dumps({
        "status": "VERIFIED_SYNTHETIC",
        "matchups": 1, "score_scenarios": 100,
        "home_win_probability": scores["home_win"]["win"],
        "first_td_outcomes_normalized": True,
        "betting_approved": False,
    }), flush=True)


if __name__ == "__main__":
    main()
