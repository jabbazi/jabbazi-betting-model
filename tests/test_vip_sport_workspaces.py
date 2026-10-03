from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jabazi" / "static"


def test_professional_terminal_has_separate_sport_workspaces():
    html = (STATIC / "terminal.html").read_text()
    for sport in ("MLB", "NFL", "CFB", "NBA", "NHL"):
        assert f'data-sport="{sport}"' in html
        assert f'#sport={sport}' in html


def test_each_primary_sport_has_dedicated_model_workspace_configuration():
    js = (STATIC / "terminal.js").read_text()
    for sport in ("MLB", "NFL", "CFB", "NBA", "NHL"):
        assert f"{sport}:{{label:'{sport}'" in js
    assert "NFL Anytime TD Top 10" in js
    assert "MLB Home Run Top 10" in js
    assert "NBA Props Top 10" in js
    assert "NHL Goal Scorer Top 10" in js


def test_cfb_workspace_does_not_advertise_player_props():
    js = (STATIC / "terminal.js").read_text()
    cfb = js.split("CFB:{label:'CFB'", 1)[1].split("NBA:{label:'NBA'", 1)[0]
    assert "player_" not in cfb


def test_terminal_detail_surfaces_source_freshness_without_fabrication():
    js = (STATIC / "terminal.js").read_text()
    assert "Injury source" in js
    assert "Lineup / starter" in js
    assert "Not sourced" in js
    assert "slate?sport=" in js


def test_terminal_includes_evidence_grounded_ask_jabbazi():
    js = (STATIC / "terminal.js").read_text()
    assert "Ask JABBAZI" in js
    assert "ask?" in js


def test_session_poll_does_not_full_rerender_active_view():
    js = (STATIC / "terminal.js").read_text()
    poll = js.split("setInterval(()=>", 1)[1].split("},30000);", 1)[0]
    assert "get('me')" in poll
    assert "render()" not in poll
    assert "replaceChildren()" not in poll


def test_extreme_disagreement_is_safety_review_not_quarantine():
    data = (ROOT / "src" / "jabazi" / "vip" / "data.py").read_text()
    assert "anomaly == 'EXTREME_DISAGREEMENT'" in data
    assert "'SAFETY REVIEW' if safety_review" in data
    assert "anomaly == 'QUARANTINED'" in data
