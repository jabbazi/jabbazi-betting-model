"""Regression tests for bounded sport-specific slate discovery."""
from datetime import UTC, date, datetime

from jabazi.boost_scope import BoostScope
from jabazi.boost_slate import inspect_sport_slate
from jabazi.providers.balldontlie import BallDontLieError


class FakeProvider:
    def __init__(self, games, props=None, complete=True):
        self.games = games
        self.props = props or {}
        self.complete = complete
        self.calls = []

    def fetch_all_pages(self, sport, resource, params, *, max_pages):
        self.calls.append((sport, resource, tuple(params)))
        if resource == "games":
            return {"data": self.games, "complete": self.complete, "pages": 1}
        gid = dict(params)["game_id"]
        value = self.props.get(gid, [])
        if isinstance(value, Exception):
            raise value
        return {"data": value, "complete": True, "pages": 1}


def game(game_id, sport="nba", state="scheduled", day="2026-10-28"):
    return {"id": game_id, "status_state": state,
            ("game_date" if sport == "nhl" else "date"): day}


def quote(identifier, game_id):
    return {"id": identifier, "game_id": game_id, "player_id": 12,
            "vendor": "draftkings", "prop_type": "points",
            "line_value": "1.5",
            "market": {"type": "over_under", "over_odds": -110,
                       "under_odds": -110},
            "updated_at": datetime.now(UTC).isoformat()}


def test_complete_nhl_slate_is_sport_isolated_and_never_claims_probabilities():
    provider = FakeProvider(
        [game(1, "nhl"), game(2, "nhl", state="final")],
        {1: [quote(400, 1)]},
    )
    report = inspect_sport_slate(
        provider, BoostScope("icehockey_nhl"),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "FULL"
    assert report.games_eligible == 1
    assert report.games_skipped == 1
    assert report.odds_report.odds_rows == 1
    assert report.player_probabilities_verified is False
    assert [c[0] for c in provider.calls] == ["nhl", "nhl"]
    assert [c[1] for c in provider.calls] == ["games", "props"]


def test_game_cap_stops_before_paid_prop_fetch():
    provider = FakeProvider([game(1), game(2)])
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba"),
        target_date=date(2026, 10, 28), max_games=1,
    )
    assert report.coverage == "PARTIAL"
    assert "GAME_CAP_REACHED_NO_PARTIAL_SCAN" in report.errors
    assert report.odds_report is None
    assert len(provider.calls) == 1


def test_unknown_lifecycle_never_claims_full_slate():
    provider = FakeProvider([game(1, state="unknown")])
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba"),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "PARTIAL"
    assert "GAME_LIFECYCLE_UNVERIFIED" in report.errors
    assert len(provider.calls) == 1


def test_incomplete_games_pagination_stops_paid_requests():
    provider = FakeProvider([game(1)], complete=False)
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba"),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "FAILED"
    assert "GAME_DISCOVERY:INCOMPLETE_GAME_PAGINATION" in report.errors
    assert len(provider.calls) == 1


def test_duplicate_game_identity_fails_closed():
    provider = FakeProvider([game(1), game(1)])
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba"),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "PARTIAL"
    assert "DUPLICATE_GAME_ID" in report.errors
    assert report.odds_report is None


def test_paid_prop_failure_preserves_partial_coverage():
    provider = FakeProvider(
        [game(1), game(2)],
        {1: [quote(11, 1)],
         2: BallDontLieError("HTTP_429")},
    )
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba"),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "PARTIAL"
    assert report.odds_report.games_succeeded == 1
    assert "game:2:HTTP_429" in report.errors


def test_promotion_game_subset_limits_paid_requests():
    provider = FakeProvider(
        [game(1), game(2)],
        {2: [quote(12, 2)]},
    )
    report = inspect_sport_slate(
        provider, BoostScope("basketball_nba", frozenset({"2"})),
        target_date=date(2026, 10, 28),
    )
    assert report.coverage == "FULL"
    assert report.games_eligible == 1
    assert [c[1] for c in provider.calls] == ["games", "props"]
    assert dict(provider.calls[1][2])["game_id"] == 2


def test_nfl_sunday_night_utc_rollover_preserves_local_game_day():
    # The API's UTC Monday timestamp represents Sunday evening Eastern.
    provider = FakeProvider(
        [{"id": 10, "status_state": "scheduled",
          "date": "2026-11-02T01:20:00Z"}],
        {10: [quote(100, 10)]},
    )
    report = inspect_sport_slate(
        provider, BoostScope("americanfootball_nfl"),
        target_date=date(2026, 11, 1),
    )
    assert report.coverage == "FULL"
    assert report.games_eligible == 1
    assert report.odds_report.odds_rows == 1
    assert [c[0] for c in provider.calls] == ["nfl", "nfl"]


def test_nfl_adjacent_eastern_day_is_skipped_without_paid_prop_call():
    provider = FakeProvider([
        {"id": 10, "status_state": "scheduled",
         "date": "2026-11-02T01:20:00Z"},
    ])
    report = inspect_sport_slate(
        provider, BoostScope("americanfootball_nfl"),
        target_date=date(2026, 11, 2),
    )
    assert report.coverage == "NO_ELIGIBLE_GAMES"
    assert report.errors == ()
    assert report.games_skipped == 1
    assert len(provider.calls) == 1


def test_nfl_nonadjacent_calendar_day_fails_closed():
    provider = FakeProvider([
        {"id": 10, "status_state": "scheduled",
         "date": "2026-11-02T01:20:00Z"},
    ])
    report = inspect_sport_slate(
        provider, BoostScope("americanfootball_nfl"),
        target_date=date(2026, 11, 4),
    )
    assert report.coverage == "PARTIAL"
    assert "GAME_DATE_NOT_VERIFIED" in report.errors
    assert len(provider.calls) == 1


def test_nfl_naive_timestamp_is_not_assumed_utc():
    provider = FakeProvider([
        {"id": 10, "status_state": "scheduled",
         "date": "2026-11-01T20:20:00"},
    ])
    report = inspect_sport_slate(
        provider, BoostScope("americanfootball_nfl"),
        target_date=date(2026, 11, 1),
    )
    assert report.coverage == "PARTIAL"
    assert "GAME_DATE_NOT_VERIFIED" in report.errors
    assert len(provider.calls) == 1


def test_nfl_game_discovery_queries_utc_rollover_in_one_bounded_call():
    class FilterByUtcDate(FakeProvider):
        def fetch_all_pages(self, sport, resource, params, *, max_pages):
            self.calls.append((sport, resource, tuple(params)))
            if resource == "games":
                dates = [v for k, v in params if k == "dates[]"]
                assert dates == ["2026-11-01", "2026-11-02"]
                assert max_pages == 10
                # Sunday-night local game is Monday UTC; an API filtering
                # on UTC date would omit it without the second date query.
                return {
                    "data": [
                        {"id": 10, "status_state": "scheduled",
                         "date": "2026-11-02T01:20:00Z"},
                        {"id": 11, "status_state": "scheduled",
                         "date": "2026-11-03T01:15:00Z"},
                    ],
                    "pages": 1, "complete": True,
                }
            gid = dict(params)["game_id"]
            return {"data": self.props.get(gid, []),
                    "pages": 1, "complete": True}

    p = FilterByUtcDate([], {10: [quote(100, 10)]})
    report = inspect_sport_slate(
        p, BoostScope("americanfootball_nfl"),
        target_date=date(2026, 11, 1),
    )
    assert report.coverage == "FULL"
    assert report.games_eligible == 1
    assert report.games_skipped == 1
    assert report.odds_report.game_row_counts == ((10, 1),)
    assert [call[1] for call in p.calls] == ["games", "props"]


def test_nba_date_query_stays_single_day():
    p = FakeProvider([game(1)], {1: [quote(100, 1)]})
    r = inspect_sport_slate(
        p, BoostScope("basketball_nba"), target_date=date(2026, 10, 28),
    )
    assert r.coverage == "FULL"
    assert p.calls[0][2] == (("dates[]", "2026-10-28"), ("per_page", 100))


def test_nhl_date_query_stays_single_day():
    p = FakeProvider([game(1, "nhl")], {1: [quote(100, 1)]})
    r = inspect_sport_slate(
        p, BoostScope("icehockey_nhl"), target_date=date(2026, 10, 28),
    )
    assert r.coverage == "FULL"
    assert p.calls[0][2] == (("dates[]", "2026-10-28"), ("per_page", 100))
