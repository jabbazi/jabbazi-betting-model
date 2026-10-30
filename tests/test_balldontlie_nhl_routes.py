from jabazi.providers.balldontlie import PATHS


def test_documented_player_prop_routes():
    # NBA v2 uses the verified /nba-prefixed live odds path; opening historical odds
    # are separate from this live endpoint.
    assert PATHS["nba"]["props"] == "/v2/odds/player_props"
    assert PATHS["nfl"]["props"] == "/nfl/v1/odds/player_props"
    assert PATHS["nhl"]["props"] == "/nhl/v1/odds/player_props"


def test_nba_resource_prefixes_follow_provider_contract():
    assert PATHS["nba"]["teams"] == "/v1/teams"
    assert PATHS["nba"]["games"] == "/v1/games"
    assert PATHS["nba"]["stats"] == "/v1/stats"
    assert PATHS["nba"]["injuries"] == "/v1/player_injuries"


def test_nhl_resource_isolation():
    assert PATHS["nhl"]["games"] == "/nhl/v1/games"
    assert PATHS["nhl"]["teams"] == "/nhl/v1/teams"
