"""Prevent regression of paid NBA/NFL/NHL GOAT endpoint routes.

The real authenticated Render Shell verified NBA /nba/v2/odds/player_props
and NFL /nfl/v1/odds/player_props on 2026-10-29. NHL route access
remains unverified (HTTP 401 on games), not a successful entitlement.
"""
import pytest

from jabazi.providers.balldontlie import PATHS


@pytest.mark.parametrize("sport,resource,path", [
    ("nba", "teams", "/nba/v1/teams"),
    ("nba", "games", "/nba/v1/games"),
    ("nba", "stats", "/nba/v1/stats"),
    ("nba", "props", "/nba/v2/odds/player_props"),
    ("nfl", "games", "/nfl/v1/games"),
    ("nfl", "props", "/nfl/v1/odds/player_props"),
    ("nhl", "games", "/nhl/v1/games"),
    ("nhl", "props", "/nhl/v1/odds/player_props"),
])
def test_goat_sport_routes_are_explicit_and_sport_scoped(sport, resource, path):
    assert PATHS[sport][resource] == path


def test_nba_routes_cannot_fall_back_to_root_v1_v2():
    assert all(path.startswith("/nba/") for path in PATHS["nba"].values())
