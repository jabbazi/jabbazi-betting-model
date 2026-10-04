import json
from pathlib import Path

from tools.bootstrap_discord import resolve_role
from jabazi.discord_bot import BotConfig, validate_target


def test_compact_discord_blueprint_is_small_and_keeps_core_surfaces():
    blueprint = json.loads(Path("docs/discord/server_blueprint.json").read_text())
    categories = blueprint["categories"]
    channels = [name for category in categories for name in category["channels"]]
    assert len(categories) <= 8
    assert len(channels) <= 20
    assert len(channels) == len(set(channels))
    assert not {"best-two-parlay", "parlays-sgps", "promo-boosts"} & set(channels)
    for required in (
        "welcome",
        "jabbazi-main-card",
        "daily-moneyline-cheat-sheet",
        "vip-research",
        "scanner-status",
        "results",
        "support",
    ):
        assert required in channels


def test_vip_role_resolution_prefers_configured_id(monkeypatch):
    roles = [
        {"id": "11", "name": "VIP"},
        {"id": "22", "name": "VIP"},
    ]
    monkeypatch.setenv("JABBAZI_DISCORD_VIP_ROLE_ID", "22")
    assert resolve_role(
        roles, env_name="JABBAZI_DISCORD_VIP_ROLE_ID", fallback_name="VIP"
    )["id"] == "22"


def test_vip_role_resolution_tolerates_duplicate_names_without_id(monkeypatch):
    monkeypatch.delenv("JABBAZI_DISCORD_VIP_ROLE_ID", raising=False)
    roles = [
        {"id": "11", "name": "VIP"},
        {"id": "22", "name": "VIP"},
    ]
    assert resolve_role(
        roles, env_name="JABBAZI_DISCORD_VIP_ROLE_ID", fallback_name="VIP"
    )["name"] == "VIP"


def test_configured_vip_role_is_allowed_on_private_target():
    config = BotConfig(
        guild=1,
        owner=2,
        status_channel=3,
        sheets_channel=4,
        viewer_roles=frozenset(),
        vip_role=55,
    )
    document = {
        "guild_id": "1",
        "id": "4",
        "type": 0,
        "permission_overwrites": [
            {"id": "1", "type": 0, "allow": "0", "deny": str(1 << 10)},
            {"id": "55", "type": 0, "allow": str((1 << 10) | (1 << 11) | (1 << 16)), "deny": "0"},
        ],
    }
    validate_target(document, config, bot_id=99)
