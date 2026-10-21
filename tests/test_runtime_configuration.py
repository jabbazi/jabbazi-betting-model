"""A missing production bankroll must never become the development balance."""

import pytest

from jabazi.runtime import configuration


@pytest.mark.parametrize("bankroll", [None, "", "   "])
def test_production_requires_explicit_bankroll(monkeypatch, tmp_path, bankroll):
    monkeypatch.chdir(tmp_path)  # No project .env can supply the missing value.
    monkeypatch.setenv("JABAZI_ENV", "production")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", "postgresql://unused/test")
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    if bankroll is None:
        monkeypatch.delenv("JABAZI_BANKROLL", raising=False)
        assert "Production requires an explicit JABAZI_BANKROLL" in configuration()[2]
    else:
        monkeypatch.setenv("JABAZI_BANKROLL", bankroll)
        # Blank numeric input fails parsing before the runtime can start.
        with pytest.raises(ArithmeticError):
            configuration()


def test_explicit_production_bankroll_is_retained(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JABAZI_ENV", "production")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", "postgresql://unused/test")
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    monkeypatch.setenv("JABAZI_BANKROLL", "840.25")
    settings, _, errors = configuration()
    assert str(settings.bankroll) == "840.25"
    assert not errors
