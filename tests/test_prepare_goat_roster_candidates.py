from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tools import prepare_goat_roster_candidates as probe
from jabazi.providers.balldontlie import BallDontLieError

NOW = datetime.now(UTC)
KICKOFF = (NOW + timedelta(hours=3)).isoformat()


def quote():
    return {"sport": "basketball_nba", "raw": {
        "game_id": 123, "player_id": 19, "prop_type": "points",
        "line_value": 22.5, "vendor": "PRIVATE_BOOK",
        "updated_at": NOW.isoformat()}}


def bdl():
    return {"id": 19, "first_name": "Private", "last_name": "Athlete",
            "team": {"abbreviation": "BOS"}, "jersey_number": "7"}


def source():
    return {"source_namespace": "ESPN", "source_player_id": "ESPN_SECRET_ID",
            "full_name": "Private Athlete", "team_abbreviation": "BOS",
            "jersey_number": 7, "source_observed_at": NOW.isoformat()}


class Provider:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = [bdl()] if rows is None else rows

    def fetch_all_pages(self, sport, resource, params, *, max_pages):
        self.calls.append((sport, resource, params, max_pages))
        assert resource == "players"
        assert ("player_ids[]", 19) in params
        assert ("per_page", 100) in params
        return {"data": self.rows, "pages": 1, "complete": True}


def test_nba_live_directory_to_source_candidate_remains_unapproved(monkeypatch):
    monkeypatch.setattr(probe, "collect_boost_odds", lambda *args, **kwargs:
        SimpleNamespace(coverage="FULL", odds_rows=1, rows=(quote(),)))
    provider = Provider()
    report = probe.audit_candidate_feed(
        provider, sport="NBA", game_id=123, event_starts_at=KICKOFF,
        source_loader=lambda teams: [source()],
    )
    assert report["status"] == "CANDIDATES_ONLY"
    assert report["candidate_count"] == 1
    assert report["source_identity_reviewed"] is False
    assert report["model_probabilities_verified"] is False
    assert report["betting_enabled"] is False
    assert report["production_approved"] is False
    assert report["_private_candidates"][0]["provider_identity_verified"] is False
    safe = dict(report)
    safe.pop("_private_candidates")
    assert "ESPN_SECRET_ID" not in str(safe)
    assert "PRIVATE_BOOK" not in str(safe)
    assert provider.calls[0][0:2] == ("nba", "players")


def test_incomplete_prop_coverage_prevents_directory_call(monkeypatch):
    monkeypatch.setattr(probe, "collect_boost_odds", lambda *args, **kwargs:
        SimpleNamespace(coverage="PARTIAL", odds_rows=1, rows=(quote(),)))
    provider = Provider()
    report = probe.audit_candidate_feed(
        provider, sport="NBA", game_id=123, event_starts_at=KICKOFF,
        source_loader=lambda teams: [source()],
    )
    assert report["status"] == "UNAVAILABLE"
    assert provider.calls == []


def test_incomplete_player_directory_fails_closed(monkeypatch):
    monkeypatch.setattr(probe, "collect_boost_odds", lambda *args, **kwargs:
        SimpleNamespace(coverage="FULL", odds_rows=1, rows=(quote(),)))
    report = probe.audit_candidate_feed(
        Provider(rows=[]), sport="NBA", game_id=123,
        event_starts_at=KICKOFF, source_loader=lambda teams: [source()],
    )
    assert report["reason"] == "PLAYER_DIRECTORY_INCOMPLETE_OR_DUPLICATE"
    assert report["candidate_count"] == 0


def test_provider_401_is_redacted(monkeypatch):
    def reject(*args, **kwargs):
        raise BallDontLieError("HTTP_401")
    monkeypatch.setattr(probe, "collect_boost_odds", reject)
    report = probe.audit_candidate_feed(
        Provider(), sport="NBA", game_id=123, event_starts_at=KICKOFF,
        source_loader=lambda teams: [source()],
    )
    assert report["reason"] == "PROVIDER_OR_SOURCE_EVIDENCE_UNAVAILABLE"
    assert report["production_approved"] is False


@pytest.mark.parametrize("sport,gid", [("NHL", 123), ("NBA", 0),
                                       ("NFL", True), ("NBA", -5)])
def test_invalid_sport_or_game_rejected(sport, gid):
    with pytest.raises(ValueError):
        probe.audit_candidate_feed(Provider(), sport=sport, game_id=gid,
                                   event_starts_at=KICKOFF)


def test_nfl_automatic_source_loader_can_generate_unapproved_candidate(monkeypatch):
    nfl_quote = {"sport": "americanfootball_nfl", "raw": {
        "game_id": 123, "player_id": 19, "prop_type": "passing_yards",
        "line_value": 220.5, "vendor": "PRIVATE_BOOK",
        "updated_at": NOW.isoformat()}}
    monkeypatch.setattr(probe, "collect_boost_odds", lambda *args, **kwargs:
        SimpleNamespace(coverage="FULL", odds_rows=1, rows=(nfl_quote,)))
    nfl_bdl = bdl() | {"position_abbreviation": "QB"}
    nfl_source = source() | {"source_namespace": "NFLVERSE",
                             "position_abbreviation": "QB"}
    report = probe.audit_candidate_feed(
        Provider(rows=[nfl_bdl]), sport="NFL", game_id=123,
        event_starts_at=KICKOFF, source_loader=lambda teams: [nfl_source],
    )
    assert report["candidate_count"] == 1
    assert report["status"] == "CANDIDATES_ONLY"
    assert report["source_identity_reviewed"] is False


def test_private_candidate_file_is_exclusive_and_owner_only(tmp_path):
    path = tmp_path / "candidates.json"
    probe._write_private_candidates(path, [{"bdl_player_id": 19}])
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        probe._write_private_candidates(path, [])
