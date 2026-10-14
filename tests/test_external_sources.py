import json

from jabazi.research.external_sources import external_research_sources


KEY_VARS = (
    "JABBAZI_UNABATED_API_KEY",
    "JABBAZI_PFF_API_KEY",
    "JABBAZI_OPTICODDS_API_KEY",
    "JABBAZI_ODDSJAM_API_KEY",
)


def test_external_research_registry_is_complete_and_non_authoritative(monkeypatch):
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("JABBAZI_OUTLIER_WEB_ENABLED", raising=False)
    monkeypatch.delenv("JABBAZI_ACTION_WEB_ENABLED", raising=False)

    sources = external_research_sources()

    assert set(sources) == {
        "unabated",
        "outlier",
        "pff",
        "action_network",
        "oddsjam_opticodds",
    }
    assert sources["unabated"]["enabled"] is False
    assert sources["pff"]["enabled"] is False
    assert sources["oddsjam_opticodds"]["enabled"] is False
    assert sources["outlier"]["enabled"] is True
    assert sources["action_network"]["enabled"] is True
    assert all(source["cash_influence"] is False for source in sources.values())


def test_external_research_registry_detects_credentials_without_exposing_them(monkeypatch):
    secrets = {
        "JABBAZI_UNABATED_API_KEY": "unabated-super-secret",
        "JABBAZI_PFF_API_KEY": "ak_live_pff-super-secret",
        "JABBAZI_OPTICODDS_API_KEY": "optic-super-secret",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    sources = external_research_sources()
    rendered = json.dumps(sources)

    assert sources["unabated"]["credential_configured"] is True
    assert sources["pff"]["credential_configured"] is True
    assert sources["oddsjam_opticodds"]["credential_configured"] is True
    assert all(secret not in rendered for secret in secrets.values())


def test_external_web_validation_sources_can_be_disabled(monkeypatch):
    monkeypatch.setenv("JABBAZI_OUTLIER_WEB_ENABLED", "false")
    monkeypatch.setenv("JABBAZI_ACTION_WEB_ENABLED", "0")

    sources = external_research_sources()

    assert sources["outlier"]["enabled"] is False
    assert sources["action_network"]["enabled"] is False
