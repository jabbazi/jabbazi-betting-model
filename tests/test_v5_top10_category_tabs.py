"""V5 Top 10 category-navigation contract for the existing VIP terminal."""
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "src/jabazi/static/terminal.js").read_text()


def test_nba_top10_has_separate_points_rebounds_assists_and_combos():
    for label, key in [
        ("Points", "player_points"), ("Rebounds", "player_rebounds"),
        ("Assists", "player_assists"), ("Threes", "player_threes"),
        ("PRA", "player_points_rebounds_assists"),
        ("Points + Rebounds", "player_points_rebounds"),
    ]:
        assert f"['{label}','{key}']" in JS


def test_nfl_nhl_mlb_top10_categories_and_exact_market_filter():
    for market in ("player_anytime_td", "player_reception_yds", "player_shots_on_goal",
                   "player_total_saves", "batter_home_runs", "pitcher_strikeouts"):
        assert market in JS
    assert "categories.some(([,key])=>key===selected)" in JS
    assert "((d.player_markets||{})[market]||[])" in JS
    assert "((d.player_market_value||{})[market]||[])" in JS


def test_no_market_line_masquerades_as_mean_projection():
    assert "This is NOT a projected points/rebounds/assists average" in JS
    assert "sportsbook lines are not substituted for projections" in JS
    assert "The app will not invent ten players" in JS


def test_cfb_player_market_remains_disabled():
    assert "Player-prop markets are disabled under the existing Louisiana policy" in JS
    assert "sport==='CFB'" in JS
