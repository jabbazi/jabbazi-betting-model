"""Matrix tests use synthetic function fixtures, never paid provider calls."""
from datetime import date

import pytest

from tools import boost_live_acceptance_matrix as matrix

DAY = date(2026, 10, 28)


def report(sport, *, count=10, coverage="FULL", errors=()):
    return {
        "sport": sport,
        "coverage": coverage,
        "games_eligible": 2,
        "games_with_prop_response": 2,
        "eligible_quote_rows": count,
        "errors": list(errors),
        "paid_endpoint_sample_access_observed": True,
    }


def test_all_three_nonempty_sport_only_samples_still_not_approved(monkeypatch):
    called = []
    def probe(provider, *, sport, calendar_date, max_games):
        called.append((sport, calendar_date, max_games))
        return report(sport)
    monkeypatch.setattr(matrix, "audit_sport", probe)
    result = matrix.audit_matrix(
        object(), target_date=DAY, max_games=5, runtime_commit="a" * 40,
    )
    assert [x[0] for x in called] == ["NBA", "NFL", "NHL"]
    assert all(x[1] == DAY and x[2] == 5 for x in called)
    assert result["all_three_paid_quote_coverage_observed"] is True
    assert result["joint_probability_calibration_validated"] is False
    assert result["sportsbook_combined_sgp_quote_verified"] is False
    assert result["production_approved"] is False
    assert result["betting_decision"] == "PASS"
    assert result["environment_commit"] == "a" * 40


def test_empty_paid_game_does_not_count_as_coverage(monkeypatch):
    monkeypatch.setattr(
        matrix, "audit_sport",
        lambda provider, *, sport, calendar_date, max_games:
            report(sport, count=0 if sport == "NBA" else 10),
    )
    result = matrix.audit_matrix(object(), target_date=DAY)
    assert result["sports"]["NBA"]["coverage"] == "FULL"
    assert result["all_three_paid_quote_coverage_observed"] is False
    assert result["betting_decision"] == "PASS"


def test_provider_429_halts_remaining_sports_without_retry(monkeypatch):
    calls = []
    def probe(provider, *, sport, calendar_date, max_games):
        calls.append(sport)
        return report(sport, coverage="FAILED", errors=("game:123:HTTP_429",))
    monkeypatch.setattr(matrix, "audit_sport", probe)
    result = matrix.audit_matrix(object(), target_date=DAY)
    assert calls == ["NBA"]
    assert result["halt_reason"] == "PROVIDER_ENTITLEMENT_RATE_LIMIT_OR_BUDGET_FAILURE"
    assert result["sports"]["NFL"]["coverage"] == "NOT_CHECKED"
    assert result["sports"]["NHL"]["coverage"] == "NOT_CHECKED"
    assert not result["all_three_paid_quote_coverage_observed"]


def test_malformed_runtime_evidence_never_outputs_secret(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Secret credential must not leak")
    monkeypatch.setattr(matrix, "audit_sport", fail)
    result = matrix.audit_matrix(
        object(), target_date=DAY, runtime_commit="TOP_SECRET",
    )
    assert result["environment_commit"] is None
    assert result["all_three_paid_quote_coverage_observed"] is False
    assert result["betting_decision"] == "PASS"
    assert "TOP_SECRET" not in str(result)
    assert "Secret credential" not in str(result)


def test_missing_secret_is_quota_free(monkeypatch, capsys):
    monkeypatch.delenv("JABBAZI_BALLDONTLIE_API_KEY", raising=False)
    assert matrix.main(["--date", "2026-10-28"]) == 2
    output = capsys.readouterr().out
    assert "PROVIDER_NOT_CONFIGURED" in output
    assert "production_approved" in output


@pytest.mark.parametrize("cap", [0, 26])
def test_invalid_slate_cap_is_rejected(cap):
    with pytest.raises(ValueError, match="bounded"):
        matrix.audit_matrix(object(), target_date=DAY, max_games=cap)


def test_incomplete_single_sport_blocks_matrix(monkeypatch):
    monkeypatch.setattr(
        matrix, "audit_sport",
        lambda provider, *, sport, calendar_date, max_games:
            report(sport, coverage="PARTIAL" if sport == "NHL" else "FULL"),
    )
    result = matrix.audit_matrix(object(), target_date=DAY)
    assert not result["all_three_paid_quote_coverage_observed"]
    assert all(s in result["sports"] for s in ("NBA", "NFL", "NHL"))
