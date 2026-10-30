from datetime import UTC, datetime

import pytest

from jabazi import boost_nfl_nflverse_roster as roster


def test_public_nflverse_roster_source_with_gsis_id_and_jersey(monkeypatch):
    csv_bytes = (
        "season,team,position,jersey_number,full_name,gsis_id,status\n"
        "2026,NE,QB,10,Drake Maye,00-0030001,ACT\n"
        "2026,BUF,QB,17,Josh Allen,00-0030002,ACT\n"
        "2025,NE,QB,10,Old Player,00-0030003,ACT\n"
    ).encode()
    called = []
    def fetch(url, *, max_bytes):
        called.append((url, max_bytes))
        return csv_bytes
    monkeypatch.setattr(roster, "_fetch_bytes", fetch)
    rows = roster.fetch_nfl_nflverse_roster(
        {"NE"}, now=datetime(2026, 10, 29, tzinfo=UTC)
    )
    assert len(rows) == 1
    assert rows[0]["source_player_id"] == "00-0030001"
    assert rows[0]["source_namespace"] == "NFLVERSE"
    assert rows[0]["jersey_number"] == "10"
    assert len(rows[0]["source_response_sha256"]) == 64
    assert "roster_2026.csv" in called[0][0]


def test_missing_required_gsis_id_column_fails_closed(monkeypatch):
    monkeypatch.setattr(roster, "_fetch_bytes",
                        lambda url, **kwargs: b"season,team,position,jersey_number,full_name\n2026,NE,QB,10,Player\n")
    with pytest.raises(ValueError, match="schema mismatch"):
        roster.fetch_nfl_nflverse_roster(
            {"NE"}, now=datetime(2026, 10, 29, tzinfo=UTC)
        )


@pytest.mark.parametrize("teams", [[], {"NE", "BUF", "DAL", "MIA", "KC"}, {"???"}])
def test_invalid_team_scope_rejected_before_download(monkeypatch, teams):
    monkeypatch.setattr(roster, "_fetch_bytes",
                        lambda url, **kwargs: (_ for _ in ()).throw(AssertionError("download")))
    with pytest.raises(ValueError):
        roster.fetch_nfl_nflverse_roster(teams, now=datetime.now(UTC))
