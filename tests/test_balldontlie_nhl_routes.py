from jabazi.providers.balldontlie import PATHS

def test_documented_player_prop_routes():
    assert PATHS["nba"]["props"] == "/nba/v2/odds/player_props"
    assert PATHS["nfl"]["props"] == "/nfl/v1/odds/player_props"
    assert PATHS["nhl"]["props"] == "/nhl/v1/odds/player_props"

def test_nhl_resource_isolation():
    assert PATHS["nhl"]["games"] == "/nhl/v1/games"
    assert PATHS["nhl"]["teams"] == "/nhl/v1/teams"
