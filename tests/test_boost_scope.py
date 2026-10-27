from datetime import datetime, timedelta, timezone
import pytest
from jabazi.boost_scope import BoostScope, eligible_rows, scope_from_text


def test_sport_isolation():
    scope = scope_from_text("Best NHL boost", markets=["player_goals"])
    assert scope.sport == "icehockey_nhl"
    assert scope.markets == frozenset(["player_goals"])
    with pytest.raises(ValueError):
        scope_from_text("NBA NFL boost")
    with pytest.raises(ValueError):
        scope_from_text("best boost")


def test_only_eligible_fresh_rows():
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=1)).isoformat()
    base = dict(sport="icehockey_nhl", event_id="game1", player_id="p1",
                market="player_goals", line=0.5, side="over",
                provider="paid", probability=0.35, observed_at=stamp)
    rows = [base, dict(base), dict(base, sport="basketball_nba"),
            dict(base, market="player_assists"),
            dict(base, probability=1.5),
            dict(base, observed_at=(now-timedelta(days=1)).isoformat())]
    found, audit = eligible_rows(BoostScope("icehockey_nhl",
        frozenset(["game1"]), frozenset(["player_goals"])),
        rows, observed_after=now-timedelta(minutes=5))
    assert len(found) == 1
    assert audit["wrong_sport"] == 1
    assert audit["out_of_scope"] == 1
    assert audit["invalid"] == 1
    assert audit["stale"] == 1
    assert audit["duplicates"] == 1
    assert audit["coverage"] == "UNVERIFIED_PROVIDER_COMPLETENESS"
