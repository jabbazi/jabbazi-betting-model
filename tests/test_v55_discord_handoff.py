"""Regression contract for Discord VIP handoff to the existing V5.5 terminal."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/jabazi"


def test_bang_vip_and_slash_vip_use_same_existing_portal():
    discord = (ROOT / "discord_bot.py").read_text()
    access = (ROOT / "member_access.py").read_text()
    assert 'link = portal_origin() + "/vip#access=" + ticket' in discord
    assert 'title="Open JABBAZI V5.5 VIP"' in discord
    assert 'JABBAZI V5.5 VIP — updated Top 10' in discord
    assert 'def portal_origin():' in access
    assert 'JABBAZI_MEMBER_ORIGIN' in access
    assert '"/vip#access="' in discord


def test_direct_ev_slash_command_and_expected_registration():
    discord = (ROOT / "discord_bot.py").read_text()
    script = (ROOT / "static/terminal.js").read_text()
    assert '@self.tree.command(name="ev"' in discord
    assert 'await open_research(interaction, "ev")' in discord
    assert '"playoftheday", "ev"}' in discord
    assert "'top10','ev','board','sheets'" in script
    assert "else if(route==='ev')" in script


def test_existing_member_authentication_remains_required():
    from fastapi.testclient import TestClient
    from jabazi.api import app

    client = TestClient(app)
    r = client.get("/v1/vip/ev-center")
    assert r.status_code in (401, 403, 503)
    assert "expected_profit_per_50" not in r.text
