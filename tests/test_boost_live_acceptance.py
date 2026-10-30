"""No network, credentials or licensed payloads are used in these tests."""
from datetime import UTC, date, datetime

import pytest

from jabazi.providers.balldontlie import BallDontLieError
from tools.boost_live_acceptance import audit_sport, main


class FakeProvider:
    def __init__(self, *, games, props=None, error=None):
        self.games = games
        self.props = props or {}
        self.error = error
        self.calls = []

    def fetch_all_pages(self, sport, resource, params, *, max_pages):
        self.calls.append((sport, resource, tuple(params), max_pages))
        if resource == "games":
            return {"data": self.games, "complete": True, "pages": 1}
        if self.error is not None:
            raise self.error
        gid = dict(params)["game_id"]
        return {"data": self.props.get(gid, []), "complete": True, "pages": 1}


def game(gid, *, sport="nba", day="2026-10-28"):
    kickoff = day + "T20:00:00Z"
    output = {"id": gid, "status_state": "scheduled",
              ("game_date" if sport == "nhl" else "date"): day}
    output[{"nba": "datetime", "nfl": "date", "nhl": "start_time_utc"}[sport]] = kickoff
    return output


def quote(gid):
    return {
        "id": gid + 100, "game_id": gid, "player_id": 444,
        "vendor": "fanduel", "prop_type": "points", "line_value": "20.5",
        "market": {"type": "over_under", "over_odds": -115, "under_odds": -105},
        "updated_at": datetime.now(UTC).isoformat(),
        "protected_vendor_secret_payload": "must-never-expose",
    }


def test_sport_isolation_and_provenance_no_raw_data():
    p = FakeProvider(games=[game(42)], props={42: [quote(42)]})
    report = audit_sport(
        p, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert report["verified_future_kickoff_required"] is True
    assert report["coverage"] == "FULL"
    assert report["eligible_quote_rows"] == 1
    assert report["games_with_prop_response"] == 1
    assert report["games_with_eligible_quotes"] == 1
    priority = report["priority_market_observations"]
    assert priority["sport"] == "NBA"
    assert priority["priority_markets_observed"] == 1
    assert any(m["prop_type"] == "points" and m["games_with_any_accepted_quote"] == 1
               for m in priority["categories"])
    assert any(m["prop_type"] == "points_rebounds_assists"
               and m["observation"] == "NOT_OBSERVED"
               for m in priority["categories"])
    assert priority["source_defined_market_universe_complete"] is False
    assert report["paid_endpoint_sample_access_observed"] is True
    assert report["provider_player_hit_probabilities"] is False
    assert report["joint_calibration_validated"] is False
    assert report["production_approved"] is False
    assert report["recommendation"] == "PASS"
    assert "must-never-expose" not in str(report)
    assert [x[0] for x in p.calls] == ["nba", "nba"]
    assert p.calls[1][-1] == 1


def test_nhl_paid_scope_and_rate_limit_fail_closed():
    p = FakeProvider(
        games=[game(10, sport="nhl")], error=BallDontLieError("HTTP_429"),
    )
    report = audit_sport(
        p, sport="NHL", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
        event_ids=[10], markets=["goals"],
    )
    assert report["coverage"] == "FAILED"
    assert report["recommendation"] == "PASS"
    assert report["errors"] == ["game:10:HTTP_429"]
    assert [x[0] for x in p.calls] == ["nhl", "nhl"]


def test_large_slate_does_not_silently_truncate_or_fetch_paid_props():
    p = FakeProvider(games=[game(1), game(2), game(3)])
    report = audit_sport(
        p, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
        max_games=2,
    )
    assert report["coverage"] == "PARTIAL"
    assert "GAME_CAP_REACHED_NO_PARTIAL_SCAN" in report["errors"]
    assert len(p.calls) == 1


def test_no_games_not_confused_with_verified_odds():
    p = FakeProvider(games=[])
    report = audit_sport(
        p, sport="NFL", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert report["games_with_eligible_quotes"] == 0
    assert report["coverage"] == "NO_ELIGIBLE_GAMES"
    assert report["paid_endpoint_sample_access_observed"] is False
    assert report["recommendation"] == "PASS"


def test_missing_key_prevents_any_network(monkeypatch, capsys):
    monkeypatch.delenv("JABBAZI_BALLDONTLIE_API_KEY", raising=False)
    result = main(["--sport", "NHL", "--date", "2026-10-28"])
    assert result == 2
    output = capsys.readouterr().out
    assert "PROVIDER_NOT_CONFIGURED" in output
    assert "PASS" in output


@pytest.mark.parametrize("sport", ["MLB", "nhl", ""])
def test_reject_invalid_sport(sport):
    with pytest.raises(ValueError, match="Unsupported sport"):
        audit_sport(
            FakeProvider(games=[]), sport=sport,
            calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
        )


def test_reject_duplicate_event_scope():
    with pytest.raises(ValueError, match="Duplicate"):
        audit_sport(
            FakeProvider(games=[]), sport="NBA",
            calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
            event_ids=[12, 12],
        )


def test_paid_http_success_with_one_empty_game_is_not_full_quote_coverage():
    p = FakeProvider(
        games=[game(42), game(43)],
        props={42: [quote(42)], 43: []},
    )
    report = audit_sport(
        p, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert report["coverage"] == "FULL"  # both provider requests completed
    assert report["games_with_prop_response"] == 2
    assert report["games_with_eligible_quotes"] == 1
    assert report["eligible_quote_rows"] == 1
    assert report["production_approved"] is False
    assert report["recommendation"] == "PASS"


def test_missing_kickoff_is_not_validated_pregame_quote():
    entry = game(42)
    del entry["datetime"]
    p = FakeProvider(games=[entry], props={42: [quote(42)]})
    report = audit_sport(
        p, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert report["coverage"] == "PARTIAL"
    assert "GAME_START_UNVERIFIED" in report["errors"]
    assert [x[1] for x in p.calls] == ["games"]
    assert report["eligible_quote_rows"] == 0


def test_scheduled_label_does_not_resurrect_already_started_game():
    p = FakeProvider(games=[game(42)], props={42: [quote(42)]})
    report = audit_sport(
        p, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 21, tzinfo=UTC),
    )
    assert report["coverage"] == "PARTIAL"
    assert "GAME_ALREADY_STARTED" in report["errors"]
    assert [x[1] for x in p.calls] == ["games"]


def test_nhl_kickoff_date_inconsistent_with_game_date_fails_closed():
    entry = game(12, sport="nhl")
    entry["start_time_utc"] = "2026-10-30T02:00:00Z"
    p = FakeProvider(games=[entry], props={12: [quote(12)]})
    report = audit_sport(
        p, sport="NHL", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert report["coverage"] == "PARTIAL"
    assert "GAME_KICKOFF_DATE_MISMATCH" in report["errors"]
    assert [x[1] for x in p.calls] == ["games"]
