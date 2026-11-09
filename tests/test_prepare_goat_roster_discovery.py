from datetime import UTC, date, datetime, time, timedelta
import json

import pytest

from tools import prepare_goat_roster_candidates as probe


class Provider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def fetch_all_pages(self, sport, resource, params, *, max_pages):
        self.calls.append((sport, resource, params))
        assert resource == "games"
        return {"complete": True, "pages": 1, "data": self.rows}


def future_nba():
    start = datetime.combine((datetime.now(UTC) + timedelta(days=2)).date(),
                             time(18, 0), tzinfo=UTC)
    return {
        "id": 77, "date": start.date().isoformat(),
        "datetime": start.isoformat(), "status_state": "scheduled",
    }


def test_discovery_uses_real_scheduled_future_game_identity():
    game = future_nba()
    provider = Provider([game])
    result = probe.discover_upcoming_games(
        provider, sport="NBA", calendar_date=date.fromisoformat(game["date"]),
    )
    assert result == [(77, game["datetime"])]
    assert provider.calls[0][0:2] == ("nba", "games")


def test_duplicate_game_identity_fails_closed():
    game = future_nba()
    provider = Provider([game, game])
    with pytest.raises(ValueError, match="Duplicate provider game ID"):
        probe.discover_upcoming_games(
            provider, sport="NBA", calendar_date=date.fromisoformat(game["date"]),
        )


def test_date_probe_returns_only_sanitized_candidate_counts(monkeypatch):
    start = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    monkeypatch.setattr(probe, "discover_upcoming_games",
                        lambda *args, **kwargs: [(77, start)])
    monkeypatch.setattr(probe, "audit_candidate_feed", lambda *args, **kwargs: {
        "sport": "NBA", "status": "CANDIDATES_ONLY", "candidate_count": 2,
        "source_identity_reviewed": False,
        "betting_enabled": False, "production_approved": False,
    })
    result = probe.audit_date_candidates(
        object(), sport="NBA", calendar_date=date(2026, 10, 30),
    )
    assert result["candidate_count"] == 2
    assert result["games_considered"] == 1
    assert result["production_approved"] is False
    assert "77" not in str(result)


def test_cli_accepts_date_without_game_id_or_kickoff(monkeypatch, capsys):
    monkeypatch.setenv("JABBAZI_BALLDONTLIE_API_KEY", "PRIVATE_KEY")
    closed = []
    class FakeProvider:
        def __init__(self, key, *, budget):
            assert key == "PRIVATE_KEY"
        def close(self):
            closed.append(True)
    monkeypatch.setattr(probe, "BallDontLieProvider", FakeProvider)
    monkeypatch.setattr(probe, "audit_date_candidates", lambda *args, **kwargs: {
        "sport": "NBA", "status": "CANDIDATES_ONLY",
        "candidate_count": 1, "production_approved": False,
        "_private_candidates": [{"bdl_player_id": 77}],
    })
    code = probe.main(["--sport", "NBA", "--date", "2026-10-30"])
    output = capsys.readouterr().out
    assert code == 0
    assert json.loads(output)["candidate_count"] == 1
    assert "PRIVATE_KEY" not in output
    assert "bdl_player_id" not in output
    assert closed


def test_cli_rejects_conflicting_date_and_explicit_game():
    with pytest.raises(SystemExit):
        probe.main(["--sport", "NBA", "--date", "2026-10-30",
                    "--game-id", "77", "--starts-at", "2026-10-30T20:00:00Z"])
