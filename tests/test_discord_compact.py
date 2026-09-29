import json
from pathlib import Path

import pytest

from tools.bootstrap_discord import resolve_role


def test_compact_discord_blueprint_is_small_and_keeps_core_surfaces():
    blueprint = json.loads(Path("docs/discord/server_blueprint.json").read_text())
    categories = blueprint["categories"]
    channels = [name for category in categories for name in category["channels"]]
    assert len(categories) <= 5
    assert len(channels) <= 21
    assert len(channels) == len(set(channels))
    for required in (
        "welcome",
        "jabbazi-main-card",
        "jabbazi-sprinkles",
        "best-two-parlay",
        "vip-parlays",
        "daily-moneyline-cheat-sheet",
        "vip-research",
        "scanner-status",
        "daily-results",
        "open-a-ticket",
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


def test_vip_role_resolution_rejects_duplicate_names_without_id(monkeypatch):
    monkeypatch.delenv("JABBAZI_DISCORD_VIP_ROLE_ID", raising=False)
    roles = [
        {"id": "11", "name": "VIP"},
        {"id": "22", "name": "VIP"},
    ]
    with pytest.raises(SystemExit):
        resolve_role(
            roles, env_name="JABBAZI_DISCORD_VIP_ROLE_ID", fallback_name="VIP"
        )
