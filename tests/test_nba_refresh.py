from datetime import UTC, datetime

from jabazi.models.refresh import nba_schedule_rows


NOW = datetime(2026, 9, 28, 19, tzinfo=UTC)


def test_nba_schedule_refresh_separates_completed_and_future_games():
    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        "1,2026,2,2026-04-01T00:00:00+00:00,false,true,Boston Celtics,New York Knicks,110,101\n"
        "2,2027,2,2026-10-01T00:00:00+00:00,false,false,Los Angeles Lakers,Golden State Warriors,,\n"
    ).encode()
    games, events = nba_schedule_rows(raw, NOW)
    assert len(games) == 1
    assert games[0]["season"] == 2025
    assert games[0]["home_score"] == 110
    assert len(events) == 1
    assert events[0]["season"] == 2026
    assert events[0]["home_team"] == "Los Angeles Lakers"


def test_nba_schedule_refresh_fails_closed_on_bad_rows():
    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        ",2027,2,not-a-date,false,false,Same,Same,,\n"
    ).encode()
    games, events = nba_schedule_rows(raw, NOW)
    assert games == []
    assert events == []
